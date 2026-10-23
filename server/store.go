package main

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
)

type Message struct {
	Archived              bool            `json:"archived"`
	PrimaryClassification *Classification `json:"primary_classification,omitempty"`
	Source                string          `json:"classification_source,omitempty"`
	LLMPending            bool            `json:"llm_pending,omitempty"`
	ID                    string          `json:"message_id"`
	Sender                string          `json:"sender"`
	Body                  string          `json:"body"`
	Received              int64           `json:"received_at"`
	Subscription          int             `json:"subscription_id"`
	Slot                  int             `json:"slot"`
	Category              string          `json:"category"`
	Confidence            float64         `json:"confidence"`
	Risk                  float64         `json:"risk"`
	Review                bool            `json:"needs_review"`
	Model                 string          `json:"model_version"`
	Action                string          `json:"action"`
	Reason                string          `json:"reason"`
	Device                string          `json:"device_id"`
	Revision              int64           `json:"revision"`
	Classified            bool            `json:"classified"`
	Restored              bool            `json:"restored"`
	ClassifierAction      string          `json:"classifier_action,omitempty"`
	ClassifierReason      string          `json:"classifier_reason,omitempty"`
	ClassifierThreshold   *float64        `json:"classifier_threshold,omitempty"`
}
type Device struct {
	ID        string `json:"device_id"`
	Name      string `json:"name"`
	Role      string `json:"role,omitempty"`
	PublicKey string `json:"public_key"`
	E2EE      bool   `json:"e2ee,omitempty"`
	TokenHash string `json:"token_hash,omitempty"`
	Active    bool   `json:"active"`
	Expires   int64  `json:"expires_at"`
}
type Rules struct {
	Mode      string   `json:"mode"`
	Threshold float64  `json:"threshold"`
	Whitelist []string `json:"whitelist"`
	Blacklist []string `json:"blacklist"`
}
type Feedback struct {
	ID          string `json:"operation_id"`
	MessageID   string `json:"message_id"`
	Category    string `json:"corrected_category"`
	Status      string `json:"review_status"`
	Predicted   string `json:"predicted_category,omitempty"`
	Model       string `json:"model_version,omitempty"`
	ReviewedBy  string `json:"reviewed_by,omitempty"`
	ReviewedAt  int64  `json:"reviewed_at,omitempty"`
	WithdrawnAt int64  `json:"withdrawn_at,omitempty"`
	WithdrawnBy string `json:"withdrawn_by,omitempty"`
}
type ExportAudit struct {
	ExportID    string `json:"export_id"`
	Device      string `json:"device_id"`
	At          int64  `json:"at"`
	Purpose     string `json:"purpose"`
	IncludeText bool   `json:"include_text"`
	Count       int    `json:"count"`
}
type MessageOperation struct {
	MessageID string `json:"message_id"`
	Kind      string `json:"kind"`
}

// EncryptedMessage is an opaque client-encrypted record. The server keeps
// only routing metadata and the authenticated ciphertext envelope.
type EncryptedMessage struct {
	Deleted           bool   `json:"deleted,omitempty"`
	OperationID       string `json:"operation_id,omitempty"`
	OperationKind     string `json:"operation_kind,omitempty"`
	OperationReplayed bool   `json:"operation_replayed,omitempty"`
	BaseRevision      int64  `json:"base_revision,omitempty"`
	ID                string `json:"message_id"`
	Device            string `json:"device_id"`
	Received          int64  `json:"received_at"`
	Revision          int64  `json:"revision"`
	Ciphertext        string `json:"ciphertext"`
}
type Store struct {
	MessageAliases      map[string]string           `json:"message_aliases,omitempty"`
	E2EEEnabled         bool                        `json:"e2ee_enabled,omitempty"`
	LegacyPurged        bool                        `json:"legacy_plaintext_purged,omitempty"`
	VaultSalt           string                      `json:"vault_salt,omitempty"`
	MessageOperations   map[string]MessageOperation `json:"message_operations,omitempty"`
	EncryptedOperations map[string]MessageOperation `json:"encrypted_operations,omitempty"`
	EncryptedMessages   map[string]EncryptedMessage `json:"encrypted_messages,omitempty"`
	Exports             []ExportAudit               `json:"export_audit,omitempty"`
	LLM                 LLMSettings                 `json:"llm"`
	Messages            map[string]Message          `json:"messages"`
	Devices             map[string]Device           `json:"devices"`
	Feedback            map[string]Feedback         `json:"feedback"`
	Rules               Rules                       `json:"rules"`
	Revision            int64                       `json:"revision"`
	path                string
	key                 []byte
	db                  *sql.DB
	pgLock              *sql.Conn
	tenantID            string
}

func (s *Store) messageID(id string) string {
	if canonical, ok := s.MessageAliases[id]; ok {
		return canonical
	}
	return id
}
func openStore(path string) (*Store, error) {
	s := &Store{Messages: map[string]Message{}, Devices: map[string]Device{}, Feedback: map[string]Feedback{},
		EncryptedMessages: map[string]EncryptedMessage{},
		Rules:             Rules{Mode: "classify", Threshold: 0.95, Whitelist: []string{}, Blacklist: []string{}}, path: path}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return nil, err
	}
	var key []byte
	if encoded := os.Getenv("PRIVRELAY_STORAGE_KEY"); encoded != "" {
		var err error
		key, err = base64.StdEncoding.DecodeString(encoded)
		if err != nil {
			key, err = base64.RawStdEncoding.DecodeString(encoded)
		}
		if err != nil || len(key) != 32 {
			return nil, errors.New("PRIVRELAY_STORAGE_KEY must be base64 encoding of exactly 32 bytes")
		}
	} else {
		var err error
		key, err = os.ReadFile(path + ".key")
		if errors.Is(err, os.ErrNotExist) {
			if _, e := os.Stat(path); e == nil {
				return nil, errors.New("data exists but key is missing")
			}
			key = make([]byte, 32)
			if _, err = rand.Read(key); err != nil {
				return nil, err
			}
			if err = writePrivate(path+".key", key); err != nil {
				return nil, err
			}
			if err = syncDirectory(filepath.Dir(path)); err != nil {
				return nil, err
			}
		} else if err != nil {
			return nil, err
		}
	}
	if len(key) != 32 {
		return nil, errors.New("invalid storage key")
	}
	s.key = key
	raw, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		salt := make([]byte, 16)
		if _, err := rand.Read(salt); err != nil {
			return nil, err
		}
		s.VaultSalt = base64.RawURLEncoding.EncodeToString(salt)
		if err := s.save(); err != nil {
			return nil, err
		}
		return s, nil
	}
	if err != nil {
		return nil, err
	}
	block, _ := aes.NewCipher(key)
	gcm, _ := cipher.NewGCM(block)
	if len(raw) < gcm.NonceSize() {
		return nil, errors.New("invalid store")
	}
	plain, err := gcm.Open(nil, raw[:gcm.NonceSize()], raw[gcm.NonceSize():], []byte("PrivRelay-v1"))
	if err != nil {
		return nil, err
	}
	if err = json.Unmarshal(plain, s); err != nil {
		return nil, err
	}
	if s.EncryptedMessages == nil {
		s.EncryptedMessages = map[string]EncryptedMessage{}
	}
	if s.VaultSalt == "" {
		salt := make([]byte, 16)
		if _, err := rand.Read(salt); err != nil {
			return nil, err
		}
		s.VaultSalt = base64.RawURLEncoding.EncodeToString(salt)
		if err := s.save(); err != nil {
			return nil, err
		}
	}
	return s, nil
}
func (s *Store) save() error {
	plain, err := json.Marshal(s)
	if err != nil {
		return err
	}
	block, _ := aes.NewCipher(s.key)
	gcm, _ := cipher.NewGCM(block)
	nonce := make([]byte, gcm.NonceSize())
	if _, err = rand.Read(nonce); err != nil {
		return err
	}
	raw := gcm.Seal(nonce, nonce, plain, []byte("PrivRelay-v1"))
	if s.db != nil {
		_, err = s.db.Exec(`INSERT INTO privrelay_tenant_state (tenant_id, payload, updated_at)
			VALUES ($1, $2, now()) ON CONFLICT (tenant_id) DO UPDATE
			SET payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at`, s.tenantID, raw)
		return err
	}
	f, err := os.OpenFile(s.path+".tmp", os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	if _, err = f.Write(raw); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	if err = os.Rename(s.path+".tmp", s.path); err != nil {
		return err
	}
	// Rename is the commit point. A directory-sync failure must not roll memory
	// back behind the already-visible file. Best effort on supported filesystems.
	_ = syncDirectory(filepath.Dir(s.path))
	return nil
}

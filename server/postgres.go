package main

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"

	_ "github.com/jackc/pgx/v5/stdlib"
	"golang.org/x/crypto/hkdf"
)

const tenantSchema = `CREATE TABLE IF NOT EXISTS privrelay_tenant_state (
	tenant_id text PRIMARY KEY CHECK (length(tenant_id) BETWEEN 1 AND 128),
	payload bytea NOT NULL,
	updated_at timestamptz NOT NULL DEFAULT now()
)`

func tenantStorageKey(tenantID string, fallback []byte) ([]byte, error) {
	encoded := strings.TrimSpace(os.Getenv("PRIVRELAY_STORAGE_KEY"))
	key := fallback
	if encoded != "" {
		var err error
		key, err = base64.StdEncoding.DecodeString(encoded)
		if err != nil {
			key, err = base64.RawStdEncoding.DecodeString(encoded)
		}
		if err != nil || len(key) != 32 {
			return nil, errors.New("PRIVRELAY_STORAGE_KEY must be base64 encoding of exactly 32 bytes")
		}
	} else if len(key) != 32 {
		return nil, errors.New("PRIVRELAY_STORAGE_KEY is required for PostgreSQL storage")
	}
	derived := make([]byte, 32)
	if _, err := io.ReadFull(hkdf.New(sha256.New, key, []byte("PrivRelay-PostgreSQL-Tenant-v1"), []byte(tenantID)), derived); err != nil {
		return nil, err
	}
	return derived, nil
}

func openTenantDB(ctx context.Context, dsn, tenantID string) (*sql.DB, *sql.Conn, error) {
	if strings.TrimSpace(tenantID) == "" || len(tenantID) > 128 {
		return nil, nil, errors.New("tenant ID must contain 1 to 128 characters")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, nil, errors.New("cannot initialize PostgreSQL connection")
	}
	db.SetMaxOpenConns(8)
	if err = db.PingContext(ctx); err != nil {
		db.Close()
		return nil, nil, errors.New("cannot connect to PostgreSQL")
	}
	if _, err = db.ExecContext(ctx, tenantSchema); err != nil {
		db.Close()
		return nil, nil, errors.New("cannot initialize PostgreSQL schema")
	}
	conn, err := db.Conn(ctx)
	if err != nil {
		db.Close()
		return nil, nil, errors.New("cannot acquire PostgreSQL tenant lock")
	}
	lockName := hash(dsn + "\x00" + tenantID)
	lockBits, _ := strconv.ParseUint(lockName[:16], 16, 64)
	var acquired bool
	if err = conn.QueryRowContext(ctx, `SELECT pg_try_advisory_lock($1)`, int64(lockBits)).Scan(&acquired); err != nil || !acquired {
		conn.Close()
		db.Close()
		return nil, nil, errors.New("tenant is already active or PostgreSQL lock failed")
	}
	return db, conn, nil
}

func decodeStorePayload(raw, key []byte, tenantID string, db *sql.DB, lock *sql.Conn) (*Store, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil || len(raw) < gcm.NonceSize() {
		return nil, errors.New("invalid protected PostgreSQL tenant state")
	}
	plain, err := gcm.Open(nil, raw[:gcm.NonceSize()], raw[gcm.NonceSize():], []byte("PrivRelay-v1"))
	if err != nil {
		return nil, errors.New("cannot decrypt PostgreSQL tenant state")
	}
	s := &Store{db: db, pgLock: lock, tenantID: tenantID, key: key}
	if err = json.Unmarshal(plain, s); err != nil {
		return nil, err
	}
	if s.Messages == nil {
		s.Messages = map[string]Message{}
	}
	if s.Devices == nil {
		s.Devices = map[string]Device{}
	}
	if s.Feedback == nil {
		s.Feedback = map[string]Feedback{}
	}
	if s.EncryptedMessages == nil {
		s.EncryptedMessages = map[string]EncryptedMessage{}
	}
	if s.VaultSalt == "" {
		salt := make([]byte, 16)
		if _, err = rand.Read(salt); err != nil {
			return nil, err
		}
		s.VaultSalt = base64.RawURLEncoding.EncodeToString(salt)
		if err = s.save(); err != nil {
			return nil, err
		}
	}
	return s, nil
}

func openPostgresStore(ctx context.Context, dsn, tenantID string) (*Store, error) {
	key, err := tenantStorageKey(tenantID, nil)
	if err != nil {
		return nil, err
	}
	db, lock, err := openTenantDB(ctx, dsn, tenantID)
	if err != nil {
		return nil, err
	}
	var raw []byte
	err = db.QueryRowContext(ctx, `SELECT payload FROM privrelay_tenant_state WHERE tenant_id=$1`, tenantID).Scan(&raw)
	if err == sql.ErrNoRows {
		s := &Store{Messages: map[string]Message{}, Devices: map[string]Device{}, Feedback: map[string]Feedback{}, EncryptedMessages: map[string]EncryptedMessage{}, Rules: Rules{Mode: "classify", Threshold: 0.95, Whitelist: []string{}, Blacklist: []string{}}, key: key, db: db, pgLock: lock, tenantID: tenantID}
		salt := make([]byte, 16)
		if _, err = rand.Read(salt); err != nil {
			closeTenantDB(db, lock)
			return nil, err
		}
		s.VaultSalt = base64.RawURLEncoding.EncodeToString(salt)
		if err = s.save(); err != nil {
			closeTenantDB(db, lock)
			return nil, errors.New("cannot initialize PostgreSQL tenant state")
		}
		return s, nil
	}
	if err != nil {
		closeTenantDB(db, lock)
		return nil, errors.New("cannot read PostgreSQL tenant state")
	}
	return decodeStorePayload(raw, key, tenantID, db, lock)
}

// migrateFileStoreToPostgres copies the authenticated encrypted snapshot into
// a new tenant row. It never removes or changes the source file or its key.
func migrateFileStoreToPostgres(ctx context.Context, source *Store, dsn, tenantID string) (*Store, error) {
	db, lock, err := openTenantDB(ctx, dsn, tenantID)
	if err != nil {
		return nil, err
	}
	var exists bool
	if err = db.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM privrelay_tenant_state WHERE tenant_id=$1)`, tenantID).Scan(&exists); err != nil || exists {
		closeTenantDB(db, lock)
		return nil, errors.New("target tenant already exists or cannot be checked; refusing overwrite")
	}
	derivedKey, err := tenantStorageKey(tenantID, source.key)
	if err != nil {
		closeTenantDB(db, lock)
		return nil, err
	}
	source.db, source.pgLock, source.tenantID, source.key = db, lock, tenantID, derivedKey
	if err = source.save(); err != nil {
		closeTenantDB(db, lock)
		source.db, source.pgLock = nil, nil
		return nil, fmt.Errorf("cannot migrate encrypted file state to PostgreSQL")
	}
	return source, nil
}

func closeTenantDB(db *sql.DB, lock *sql.Conn) {
	if lock != nil {
		_, _ = lock.ExecContext(context.Background(), `SELECT pg_advisory_unlock_all()`)
		_ = lock.Close()
	}
	if db != nil {
		_ = db.Close()
	}
}

func (s *Store) close() {
	if s != nil && s.db != nil {
		closeTenantDB(s.db, s.pgLock)
		s.db, s.pgLock = nil, nil
	}
}

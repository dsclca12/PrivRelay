package main

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"path/filepath"
	"testing"
)

func e2eeRegistration(t *testing.T, code string) map[string]any {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	der, _ := x509.MarshalPKIXPublicKey(&key.PublicKey)
	public := base64.StdEncoding.EncodeToString(der)
	id, nonce := "encrypted-device-0001", randomToken()
	digest := sha256.Sum256([]byte(id + "\n" + public + "\n" + nonce + "\n" + code + "\ne2ee-v1"))
	signature, err := ecdsa.SignASN1(rand.Reader, key, digest[:])
	if err != nil {
		t.Fatal(err)
	}
	return map[string]any{"device_id": id, "name": "Synthetic E2EE device", "public_key": public, "nonce": nonce, "pairing_code": code, "signature": base64.StdEncoding.EncodeToString(signature), "e2ee": true}
}

func enableE2EEFixture(t *testing.T) (*Server, string) {
	t.Helper()
	s, _ := fixture(t)
	w := call(t, s, "POST", "/api/v1/devices/register", "", e2eeRegistration(t, s.code))
	if w.Code != 201 {
		t.Fatal(w.Code, w.Body)
	}
	var registered struct {
		Token string `json:"token"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &registered); err != nil || registered.Token == "" {
		t.Fatal(err, w.Body)
	}
	return s, registered.Token
}

func sealedFixture() EncryptedMessage {
	return EncryptedMessage{ID: "encrypted-message-0001", Received: 1000, Ciphertext: base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{1}, 40))}
}

func TestE2EERegistrationRequiresValidSignatureAndDurability(t *testing.T) {
	s, token := fixture(t)
	s.store.Messages[testMessage().ID] = testMessage()
	invalid := e2eeRegistration(t, s.code)
	invalid["signature"] = "invalid"
	if w := call(t, s, "POST", "/api/v1/devices/register", "", invalid); w.Code != 403 || s.store.E2EEEnabled || len(s.store.Messages) != 1 {
		t.Fatal("unauthorized E2EE transition", w.Code)
	}
	if w := call(t, s, "POST", "/api/v2/encrypted-messages/sync", token, encryptedBatch{Messages: []EncryptedMessage{sealedFixture()}}); w.Code != 403 {
		t.Fatal("legacy client uploaded ciphertext", w.Code)
	}
	path := s.store.path
	s.store.path = filepath.Join(t.TempDir(), "missing", "store.enc")
	if w := call(t, s, "POST", "/api/v1/devices/register", "", e2eeRegistration(t, s.code)); w.Code != 503 || s.store.E2EEEnabled || len(s.store.Messages) != 1 || s.code == "" {
		t.Fatal("failed commit enabled E2EE", w.Code)
	}
	s.store.path = path
	if w := call(t, s, "POST", "/api/v1/devices/register", "", e2eeRegistration(t, s.code)); w.Code != 201 || !s.store.E2EEEnabled || len(s.store.Messages) != 1 {
		t.Fatal("registration lost legacy messages", w.Code)
	}
	if w := call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}}); w.Code != 403 {
		t.Fatal("plaintext upload accepted after E2EE", w.Code)
	}
}

func TestE2EECiphertextCASAndRestart(t *testing.T) {
	s, token := enableE2EEFixture(t)
	message := sealedFixture()
	upload := func(m EncryptedMessage) int {
		return call(t, s, "POST", "/api/v2/encrypted-messages/sync", token, encryptedBatch{Messages: []EncryptedMessage{m}}).Code
	}
	if got := upload(message); got != 200 {
		t.Fatal(got)
	}
	original := s.store.EncryptedMessages[message.ID]
	message.Ciphertext = base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{2}, 40))
	if got := upload(message); got != 409 || s.store.EncryptedMessages[message.ID] != original {
		t.Fatal("stale update overwrote ciphertext", got)
	}
	newMessage := sealedFixture()
	newMessage.ID = "new-encrypted-message-0002"
	beforeConflict := s.snapshot()
	w := call(t, s, "POST", "/api/v2/encrypted-messages/sync", token, encryptedBatch{Messages: []EncryptedMessage{newMessage, message}})
	if w.Code != 409 || !bytes.Equal(beforeConflict, s.snapshot()) {
		t.Fatal("CAS conflict partially committed a batch", w.Code)
	}
	message.BaseRevision = original.Revision
	if got := upload(message); got != 200 {
		t.Fatal("CAS update rejected", got)
	}
	updated := s.store.EncryptedMessages[message.ID]
	if updated.BaseRevision != 0 || updated.Revision <= original.Revision {
		t.Fatal("invalid stored revision", updated)
	}
	// An ACK lost in transit can be retried with the old base revision.
	if got := upload(message); got != 200 || s.store.EncryptedMessages[message.ID].Revision != updated.Revision {
		t.Fatal("identical ciphertext retry changed revision", got)
	}
	reopened, err := openStore(s.store.path)
	if err != nil || !reopened.E2EEEnabled || reopened.EncryptedMessages[message.ID] != updated {
		t.Fatal("ciphertext not durable", err)
	}
	s = newServer(reopened, "")
	if w := call(t, s, "GET", "/api/v2/encrypted-messages", token, nil); w.Code != 200 || !bytes.Contains(w.Body.Bytes(), []byte(updated.Ciphertext)) {
		t.Fatal("encrypted pull failed", w.Code)
	}
	before := s.snapshot()
	s.store.path = filepath.Join(t.TempDir(), "missing", "store.enc")
	message.BaseRevision = updated.Revision
	message.Ciphertext = base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{3}, 40))
	if got := upload(message); got != 503 || !bytes.Equal(before, s.snapshot()) {
		t.Fatal("ciphertext storage failure did not roll back", got)
	}
}

func TestE2EESupportsMmsSizedCiphertext(t *testing.T) {
	s, token := enableE2EEFixture(t)
	message := sealedFixture()
	message.ID = "encrypted-mms-attachment-0001"
	message.Ciphertext = base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{7}, 2*1024*1024))
	w := call(t, s, "POST", "/api/v2/encrypted-messages/sync", token, encryptedBatch{Messages: []EncryptedMessage{message}})
	if w.Code != 200 {
		t.Fatalf("MMS-sized encrypted message rejected: status=%d body=%s", w.Code, w.Body.String())
	}
}

func TestE2EEMigrationNeverPurgesUnmigratedOriginals(t *testing.T) {
	s, token := enableE2EEFixture(t)
	device := "encrypted-device-0001"
	legacy := testMessage()
	legacy.Device = device
	s.store.Messages[legacy.ID] = legacy
	s.store.MessageAliases = map[string]string{"transport-alias-0001": legacy.ID}
	s.store.MessageOperations = map[string]MessageOperation{"archive-operation-0001": {MessageID: legacy.ID, Kind: "archive"}}
	s.store.Feedback["feedback-operation-0001"] = Feedback{ID: "feedback-operation-0001", MessageID: legacy.ID, Category: "personal", Status: "pending_review"}
	finish := func() int {
		return call(t, s, "POST", "/api/v2/legacy-migration", token, map[string]any{"complete": true}).Code
	}
	for _, variant := range []string{"absent", "wrong_device", "wrong_timestamp"} {
		sealed := sealedFixture()
		sealed.ID = legacy.ID
		sealed.Device = device
		sealed.Received = legacy.Received
		switch variant {
		case "absent":
			delete(s.store.EncryptedMessages, legacy.ID)
		case "wrong_device":
			sealed.Device = "another-device-0001"
			s.store.EncryptedMessages[legacy.ID] = sealed
		case "wrong_timestamp":
			sealed.Received++
			s.store.EncryptedMessages[legacy.ID] = sealed
		}
		if got := finish(); got != 409 || len(s.store.Messages) != 1 || s.store.LegacyPurged {
			t.Fatal("unmigrated original purged", variant, got)
		}
	}
	sealed := sealedFixture()
	sealed.ID = legacy.ID
	sealed.Device = device
	sealed.Received = legacy.Received
	s.store.EncryptedMessages[legacy.ID] = sealed
	path := s.store.path
	s.store.path = filepath.Join(t.TempDir(), "missing", "store.enc")
	if got := finish(); got != 503 || len(s.store.Messages) != 1 || len(s.store.MessageAliases) != 1 || len(s.store.MessageOperations) != 1 || len(s.store.Feedback) != 1 || s.store.LegacyPurged {
		t.Fatal("migration storage failure lost originals", got)
	}
	s.store.path = path
	// An E2EE client cannot individually purge another device's legacy record.
	foreign := legacy
	foreign.ID = "foreign-legacy-message-0001"
	foreign.Device = "another-device-0001"
	s.store.Messages[foreign.ID] = foreign
	foreignSealed := sealed
	foreignSealed.ID, foreignSealed.Device = foreign.ID, foreign.Device
	s.store.EncryptedMessages[foreign.ID] = foreignSealed
	foreignPurge := call(t, s, "POST", "/api/v2/legacy-migration", token, map[string]any{"message_ids": []string{foreign.ID}})
	if foreignPurge.Code != 200 || s.store.Messages[foreign.ID].ID != foreign.ID {
		t.Fatal("selective migration purged a foreign device", foreignPurge.Code)
	}
	delete(s.store.Messages, foreign.ID)
	delete(s.store.EncryptedMessages, foreign.ID)
	w := call(t, s, "POST", "/api/v2/legacy-migration", token, map[string]any{"message_ids": []string{legacy.ID}})
	if w.Code != 200 || len(s.store.Messages) != 0 || len(s.store.MessageAliases) != 0 || len(s.store.MessageOperations) != 0 || len(s.store.Feedback) != 0 || len(s.store.EncryptedMessages) != 1 {
		t.Fatal("selective migration left metadata or deleted ciphertext", w.Code)
	}
	if got := finish(); got != 200 || !s.store.LegacyPurged {
		t.Fatal("safe completion failed", got)
	}
}

func TestEncryptedOperationReplayNeverReversesLaterOperation(t *testing.T) {
	s, token := enableE2EEFixture(t)
	message := sealedFixture()
	upload := func(m EncryptedMessage) map[string]json.RawMessage {
		t.Helper()
		return decodeSyncIdentityAck(t, call(t, s, "POST", "/api/v2/encrypted-messages/sync", token, encryptedBatch{Messages: []EncryptedMessage{m}}))
	}
	upload(message)
	restore := message
	restore.OperationID, restore.OperationKind = "encrypted-restore-0001", "restore"
	restore.BaseRevision = s.store.EncryptedMessages[message.ID].Revision
	restore.Ciphertext = base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{2}, 40))
	upload(restore)
	archive := message
	archive.OperationID, archive.OperationKind = "encrypted-archive-0001", "archive"
	archive.BaseRevision = s.store.EncryptedMessages[message.ID].Revision
	archive.Ciphertext = base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{3}, 40))
	upload(archive)
	archived := s.store.EncryptedMessages[message.ID]
	if archived.OperationID != "" || archived.OperationKind != "" || archived.OperationReplayed {
		t.Fatal("transport receipt leaked into the stored record", archived)
	}
	// Clearing legacy receipts must preserve encrypted operation idempotence.
	if w := call(t, s, "POST", "/api/v2/legacy-migration", token, map[string]any{"complete": true}); w.Code != 200 || len(s.store.EncryptedOperations) != 2 {
		t.Fatal("legacy migration erased encrypted operation receipts", w.Code)
	}
	reopened, err := openStore(s.store.path)
	if err != nil {
		t.Fatal(err)
	}
	s = newServer(reopened, "")
	ack := upload(restore)
	var replayed bool
	var ciphertext string
	if json.Unmarshal(ack["operation_replayed"], &replayed) != nil || !replayed || json.Unmarshal(ack["ciphertext"], &ciphertext) != nil || ciphertext != archived.Ciphertext || s.store.EncryptedMessages[message.ID] != archived {
		t.Fatal("old restore retry reversed the later archive", ack)
	}
	conflict := restore
	conflict.OperationKind = "unarchive"
	if w := call(t, s, "POST", "/api/v2/encrypted-messages/sync", token, encryptedBatch{Messages: []EncryptedMessage{conflict}}); w.Code != 409 {
		t.Fatal("receipt accepted a different operation kind", w.Code)
	}
	conflict = restore
	conflict.ID = "different-message-0001"
	if w := call(t, s, "POST", "/api/v2/encrypted-messages/sync", token, encryptedBatch{Messages: []EncryptedMessage{conflict}}); w.Code != 409 {
		t.Fatal("receipt accepted a different message", w.Code)
	}
}

func TestEncryptedNoOpReceiptIsDurableAndFailedCommitRollsBack(t *testing.T) {
	s, token := enableE2EEFixture(t)
	message := sealedFixture()
	request := func(m EncryptedMessage) int {
		return call(t, s, "POST", "/api/v2/encrypted-messages/sync", token, encryptedBatch{Messages: []EncryptedMessage{m}}).Code
	}
	if got := request(message); got != 200 {
		t.Fatal(got)
	}
	original := s.store.EncryptedMessages[message.ID]
	message.OperationID, message.OperationKind = "encrypted-noop-0001", "restore"
	if got := request(message); got != 200 || s.store.EncryptedMessages[message.ID].Revision != original.Revision {
		t.Fatal("no-op operation changed the record", got)
	}
	reopened, err := openStore(s.store.path)
	if err != nil || reopened.EncryptedOperations[message.OperationID].MessageID != message.ID {
		t.Fatal("no-op receipt was not durable", err)
	}
	before := s.snapshot()
	s.store.path = filepath.Join(t.TempDir(), "missing", "store.enc")
	message.OperationID = "encrypted-failed-0001"
	if got := request(message); got != 503 || !bytes.Equal(before, s.snapshot()) {
		t.Fatal("failed commit retained a receipt", got)
	}
	// A new receipt may not bypass the compare-and-swap check.
	s.store.path = reopened.path
	message.Ciphertext = base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{2}, 40))
	if got := request(message); got != 409 || !bytes.Equal(before, s.snapshot()) {
		t.Fatal("CAS conflict retained a receipt", got)
	}
}

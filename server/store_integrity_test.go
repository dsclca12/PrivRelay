package main

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

func TestEncryptedStoreCorruptionNeverReplacesEvidence(t *testing.T) {
	for _, corruption := range []string{"tampered_ciphertext", "truncated", "wrong_key", "short_key", "missing_key"} {
		t.Run(corruption, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "store.enc")
			s, err := openStore(path)
			if err != nil {
				t.Fatal(err)
			}
			m := testMessage()
			s.Messages[m.ID] = m
			if err = s.save(); err != nil {
				t.Fatal(err)
			}
			raw, _ := os.ReadFile(path)
			key, _ := os.ReadFile(path + ".key")
			if bytes.Contains(raw, []byte(m.Body)) {
				t.Fatal("plaintext store")
			}
			switch corruption {
			case "tampered_ciphertext":
				raw[len(raw)-1] ^= 1
				os.WriteFile(path, raw, 0600)
			case "truncated":
				raw = raw[:5]
				os.WriteFile(path, raw, 0600)
			case "wrong_key":
				key[0] ^= 1
				os.WriteFile(path+".key", key, 0600)
			case "short_key":
				key = key[:2]
				os.WriteFile(path+".key", key, 0600)
			case "missing_key":
				os.Remove(path + ".key")
			}
			before, _ := os.ReadFile(path)
			if _, err = openStore(path); err == nil {
				t.Fatal("corrupt store opened")
			}
			after, _ := os.ReadFile(path)
			if !bytes.Equal(before, after) {
				t.Fatal("opening failure replaced ciphertext")
			}
			if corruption == "missing_key" {
				if _, err = os.Stat(path + ".key"); !os.IsNotExist(err) {
					t.Fatal("missing key was silently regenerated")
				}
			}
		})
	}
}

func TestDuplicateRestoreAndOutageReplayPreserveRevision(t *testing.T) {
	s, token := fixture(t)
	body := map[string]any{"messages": []Message{testMessage()}}
	call(t, s, "POST", "/api/v1/messages/sync", token, body)
	restore := "/api/v1/messages/" + testMessage().ID + "/restore"
	call(t, s, "POST", restore, token, map[string]string{"operation_id": "restore-retry-0001"})
	before := s.store.Messages[testMessage().ID]
	call(t, s, "POST", restore, token, map[string]string{"operation_id": "restore-retry-0001"})
	call(t, s, "POST", "/api/v1/messages/sync", token, body)
	after := s.store.Messages[testMessage().ID]
	if before.Revision != after.Revision || after.Reason != "用户恢复" || !after.Restored || after.Action != "allow" {
		t.Fatal(before, after)
	}
}

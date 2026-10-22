package main

import (
	"encoding/json"
	"path/filepath"
	"testing"
)

func TestDeduplicatedTransportIDRemainsUsableAndReservedAfterRestart(t *testing.T) {
	s, token := fixture(t)
	original := testMessage()
	alias := original
	alias.ID = "transport-retry-0001"
	for _, m := range []Message{original, alias} {
		w := call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{m}})
		if w.Code != 200 {
			t.Fatalf("upload %s: %d %s", m.ID, w.Code, w.Body)
		}
		var ack struct {
			Messages []Message `json:"messages"`
		}
		if err := json.Unmarshal(w.Body.Bytes(), &ack); err != nil || len(ack.Messages) != 1 || ack.Messages[0].ID != m.ID {
			t.Fatal("transport ID was not acknowledged", err, w.Body)
		}
	}
	reopened, err := openStore(s.store.path)
	if err != nil {
		t.Fatal(err)
	}
	s = newServer(reopened, "")
	if len(s.store.Messages) != 1 {
		t.Fatal("duplicate business message")
	}
	path := "/api/v1/messages/" + alias.ID
	if w := call(t, s, "GET", path, token, nil); w.Code != 200 {
		t.Fatal("acknowledged ID cannot be queried", w.Code)
	}
	if w := call(t, s, "POST", path+"/restore", token, map[string]string{"operation_id": "restore-alias-0001"}); w.Code != 200 || !s.store.Messages[original.ID].Restored {
		t.Fatal("acknowledged ID cannot be restored", w.Code)
	}
	feedback := map[string]string{"operation_id": "feedback-alias-0001", "corrected_category": "personal"}
	if w := call(t, s, "POST", path+"/feedback", token, feedback); w.Code != 200 || s.store.Feedback[feedback["operation_id"]].MessageID != original.ID {
		t.Fatal("alias feedback did not resolve the canonical message", w.Code, w.Body)
	}
	alias.Body = "conflicting content"
	if w := call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{alias}}); w.Code != 409 || len(s.store.Messages) != 1 {
		t.Fatal("acknowledged ID was reused for another message", w.Code)
	}
}

func TestFailedAliasCommitRollsBackReservation(t *testing.T) {
	s, token := fixture(t)
	original := testMessage()
	call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{original}})
	alias := original
	alias.ID = "transport-retry-0001"
	s.store.path = filepath.Join(t.TempDir(), "missing", "store.enc")
	w := call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{alias}})
	if w.Code != 503 || len(s.store.MessageAliases) != 0 {
		t.Fatal("failed storage commit retained an alias", w.Code, s.store.MessageAliases)
	}
}

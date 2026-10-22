package main

import (
	"encoding/json"
	"net/http/httptest"
	"testing"
)

func decodeSyncIdentityAck(t *testing.T, response *httptest.ResponseRecorder) map[string]json.RawMessage {
	t.Helper()
	if response.Code != 200 {
		t.Fatalf("sync status = %d: %s", response.Code, response.Body.String())
	}
	var payload struct {
		Messages []map[string]json.RawMessage `json:"messages"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload.Messages) != 1 {
		t.Fatalf("expected one acknowledgement, got %d", len(payload.Messages))
	}
	return payload.Messages[0]
}

func TestSyncAliasAcknowledgementPreservesCanonicalIdentity(t *testing.T) {
	s, token := fixture(t)
	original := testMessage()
	upload := func(message Message) map[string]json.RawMessage {
		t.Helper()
		return decodeSyncIdentityAck(t, call(t, s, "POST", "/api/v1/messages/sync", token,
			map[string]any{"messages": []Message{message}}))
	}
	first := upload(original)
	if _, exists := first["canonical_message_id"]; exists {
		t.Fatal("ordinary upload must omit canonical_message_id")
	}
	alias := original
	alias.ID = "alias-message-id-0002"
	checkAlias := func(ack map[string]json.RawMessage) {
		t.Helper()
		var transportID, canonicalID string
		if err := json.Unmarshal(ack["message_id"], &transportID); err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(ack["canonical_message_id"], &canonicalID); err != nil {
			t.Fatal(err)
		}
		if transportID != alias.ID || canonicalID != original.ID {
			t.Fatalf("ack identity = (%q, %q), want (%q, %q)", transportID, canonicalID, alias.ID, original.ID)
		}
	}
	checkAlias(upload(alias))
	checkAlias(upload(alias))
	if len(s.store.Messages) != 1 || s.store.Revision != 1 {
		t.Fatalf("alias upload duplicated message or revision: %d messages, revision %d", len(s.store.Messages), s.store.Revision)
	}
	reopened, err := openStore(s.store.path)
	if err != nil {
		t.Fatal(err)
	}
	if len(reopened.Messages) != 1 || reopened.Messages[original.ID].ID != original.ID {
		t.Fatalf("canonical identity was not durably preserved: %#v", reopened.Messages)
	}
	s.store = reopened
	checkAlias(upload(alias))
	detail := call(t, s, "GET", "/api/v1/messages/"+original.ID, token, nil)
	if detail.Code != 200 {
		t.Fatalf("canonical message is inaccessible: %d", detail.Code)
	}
	if _, exists := decodeMessageIdentity(t, detail)["canonical_message_id"]; exists {
		t.Fatal("canonical_message_id must be limited to sync acknowledgements")
	}
}

func decodeMessageIdentity(t *testing.T, response *httptest.ResponseRecorder) map[string]json.RawMessage {
	t.Helper()
	var message map[string]json.RawMessage
	if err := json.Unmarshal(response.Body.Bytes(), &message); err != nil {
		t.Fatal(err)
	}
	return message
}

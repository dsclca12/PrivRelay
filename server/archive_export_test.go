package main

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestArchiveSyncSearchRestoreAndRollback(t *testing.T) {
	s, token := fixture(t)
	call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}})
	op := map[string]string{"operation_id": "archive-operation-0001"}
	path := "/api/v1/messages/" + testMessage().ID
	if w := call(t, s, "POST", path+"/archive", token, op); w.Code != 200 {
		t.Fatal(w.Code, w.Body)
	}
	revision := s.store.Revision
	call(t, s, "POST", path+"/archive", token, op)
	if s.store.Revision != revision {
		t.Fatal("archive retry not idempotent")
	}
	for _, check := range []struct {
		query string
		count int
	}{{"", 0}, {"?archived=true", 1}, {"?archived=all", 1}} {
		w := call(t, s, "GET", "/api/v1/messages/search"+check.query, token, nil)
		var result struct {
			Total int `json:"total"`
		}
		json.Unmarshal(w.Body.Bytes(), &result)
		if w.Code != 200 || result.Total != check.count {
			t.Fatal(check, w.Body)
		}
	}
	if w := call(t, s, "GET", "/api/v1/messages?cursor=1", token, nil); !strings.Contains(w.Body.String(), `"archived":true`) {
		t.Fatal("archive missing from sync")
	}
	if w := call(t, s, "POST", path+"/restore", token, map[string]string{"operation_id": "restore-operation-0002"}); w.Code != 200 || s.store.Messages[testMessage().ID].Archived {
		t.Fatal("restore did not unarchive")
	}
	if w := call(t, s, "POST", path+"/archive", "", op); w.Code != 401 {
		t.Fatal("unauthorized archive")
	}
	s.store.path = "/unavailable-directory/store.enc"
	op = map[string]string{"operation_id": "archive-operation-0003"}
	if w := call(t, s, "POST", path+"/archive", token, op); w.Code != 503 || s.store.Messages[testMessage().ID].Archived {
		t.Fatal("archive commit did not rollback")
	}
}
func TestExportRequiresConsentAndApprovedFeedback(t *testing.T) {
	s, token := fixture(t)
	s.store.Messages[testMessage().ID] = testMessage()
	s.store.Feedback["approved"] = Feedback{ID: "approved", MessageID: testMessage().ID, Category: "marketing", Status: "approved"}
	s.store.Feedback["pending"] = Feedback{ID: "pending", MessageID: testMessage().ID, Category: "marketing", Status: "pending_review"}
	request := map[string]any{"purpose": "evaluation", "limit": 100}
	if w := call(t, s, "POST", "/api/v1/feedback/export", token, request); w.Code != 422 {
		t.Fatal("missing consent accepted")
	}
	request["consent"] = true
	if w := call(t, s, "POST", "/api/v1/feedback/export", "", request); w.Code != 401 {
		t.Fatal("unauthorized export")
	}
	w := call(t, s, "POST", "/api/v1/feedback/export", token, request)
	if w.Code != 200 || strings.Contains(w.Body.String(), testMessage().Body) || strings.Contains(w.Body.String(), `"text"`) || strings.Contains(w.Body.String(), `"pending"`) {
		t.Fatal("metadata export leaked body or pending feedback", w.Body)
	}
	request["include_text"] = true
	w = call(t, s, "POST", "/api/v1/feedback/export", token, request)
	if w.Code != 200 || !strings.Contains(w.Body.String(), testMessage().Body) {
		t.Fatal("authorized text missing", w.Body)
	}
	if len(s.store.Exports) != 2 || !s.store.Exports[1].IncludeText {
		t.Fatal("consent audit missing")
	}
	persisted, err := openStore(s.store.path)
	if err != nil || len(persisted.Exports) != 2 {
		t.Fatal("audit not durable", err)
	}
}

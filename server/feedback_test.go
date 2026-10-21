package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestFeedbackReviewLifecycleAndDurability(t *testing.T) {
	s, token := fixture(t)
	m := testMessage()
	m.Category, m.Model = "marketing", "synthetic-v1"
	s.store.Messages[m.ID] = m
	operation := "feedback-test-0001"
	path := "/api/v1/messages/" + m.ID + "/feedback"
	body := map[string]string{"operation_id": operation, "corrected_category": "personal"}
	if w := call(t, s, "POST", path, token, body); w.Code != 200 {
		t.Fatal(w.Code, w.Body)
	}
	for _, method := range []string{"GET", "PUT"} {
		p := "/api/v1/feedback"
		if method == "PUT" {
			p += "/" + operation
		}
		if w := call(t, s, method, p, "", nil); w.Code != 401 {
			t.Fatal("unauthorized feedback", w.Code)
		}
	}
	var page struct {
		Feedback    []Feedback     `json:"feedback"`
		Counts      map[string]int `json:"counts"`
		Corrections map[string]int `json:"corrections"`
		Total       int            `json:"total"`
	}
	w := call(t, s, "GET", "/api/v1/feedback?status=pending_review&limit=1", token, nil)
	json.Unmarshal(w.Body.Bytes(), &page)
	if w.Code != 200 || page.Total != 1 || page.Counts["pending_review"] != 1 || page.Feedback[0].Predicted != "marketing" || strings.Contains(w.Body.String(), m.Body) {
		t.Fatal("feedback provenance or privacy", w.Body)
	}
	review := map[string]string{"review_status": "approved"}
	w = call(t, s, "PUT", "/api/v1/feedback/"+operation, token, review)
	if w.Code != 200 {
		t.Fatal(w.Code, w.Body)
	}
	f := s.store.Feedback[operation]
	if f.Status != "approved" || f.ReviewedBy != "test-device-0001" || f.ReviewedAt == 0 {
		t.Fatal(f)
	}
	// Retries preserve the original review and never reopen it.
	call(t, s, "PUT", "/api/v1/feedback/"+operation, token, review)
	w = call(t, s, "POST", path, token, body)
	if !strings.Contains(w.Body.String(), "approved") || s.store.Feedback[operation] != f {
		t.Fatal("retry reset review", w.Body)
	}
	if !reflect.DeepEqual(s.store.Messages[m.ID], m) {
		t.Fatal("review changed the message")
	}
	if w = call(t, s, "PUT", "/api/v1/feedback/"+operation, token, map[string]string{"review_status": "rejected"}); w.Code != 409 {
		t.Fatal(w.Code)
	}
	w = call(t, s, "GET", "/api/v1/feedback?status=approved", token, nil)
	json.Unmarshal(w.Body.Bytes(), &page)
	if page.Counts["pending_review"] != 0 || page.Counts["approved"] != 1 || page.Corrections["marketing→personal"] != 1 {
		t.Fatal(w.Body)
	}
	if w = call(t, s, "GET", "/api/v1/status", token, nil); !strings.Contains(w.Body.String(), `"pending_feedback":0`) {
		t.Fatal(w.Body)
	}
	reopened, err := openStore(s.store.path)
	if err != nil || reopened.Feedback[operation] != f {
		t.Fatal("review not durable", err)
	}
	for _, q := range []string{"limit=51", "limit=0", "offset=-1", "offset=x", "status=unknown"} {
		if w = call(t, s, "GET", "/api/v1/feedback?"+q, token, nil); w.Code != 400 {
			t.Fatal(q, w.Code)
		}
	}
	if w = call(t, s, "PUT", "/api/v1/feedback/"+operation, token, map[string]string{"review_status": "pending_review"}); w.Code != 422 {
		t.Fatal(w.Code)
	}
	if w = call(t, s, "PUT", "/api/v1/feedback/missing", token, review); w.Code != 404 {
		t.Fatal(w.Code)
	}
}

func TestFeedbackReviewRollbackAndLegacySnapshot(t *testing.T) {
	s, token := fixture(t)
	m := testMessage()
	m.Category, m.Model = "service", "legacy-model"
	s.store.Messages[m.ID] = m
	f := Feedback{ID: "legacy-feedback-01", MessageID: m.ID, Category: "personal", Status: "pending_review"}
	s.store.Feedback[f.ID] = f
	w := call(t, s, "GET", "/api/v1/feedback", token, nil)
	if !strings.Contains(w.Body.String(), "legacy-model") || s.store.Feedback[f.ID] != f {
		t.Fatal("legacy read mutated state", w.Body)
	}
	// Force a disk failure without depending on OS permissions.
	blocked := filepath.Join(t.TempDir(), "file")
	os.WriteFile(blocked, []byte("blocked"), 0600)
	s.store.path = filepath.Join(blocked, "store.enc")
	w = call(t, s, "PUT", "/api/v1/feedback/"+f.ID, token, map[string]string{"review_status": "rejected"})
	if w.Code != 503 || s.store.Feedback[f.ID] != f {
		t.Fatal("failed review was acknowledged", w.Code, w.Body)
	}
}

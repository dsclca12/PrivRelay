package main

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
)

func TestJSONRequestLimitsRemainBounded(t *testing.T) {
	s, token := fixture(t)
	for _, test := range []struct {
		path  string
		limit int
	}{
		{"/api/v1/messages/sync", 3 * 1024 * 1024},
		{"/api/v1/filter/rules", 512 * 1024},
	} {
		r := httptest.NewRequest("PUT", test.path, strings.NewReader(`{"messages":[],"padding":"`+strings.Repeat("x", test.limit)+`"}`))
		if strings.HasSuffix(test.path, "/sync") {
			r.Method = "POST"
		}
		r.Header.Set("Authorization", "Bearer "+token)
		w := httptest.NewRecorder()
		s.handler().ServeHTTP(w, r)
		if w.Code != 413 || len(s.store.Messages) != 0 {
			t.Fatalf("oversized request at %s: %d", test.path, w.Code)
		}
	}
	// A small object followed by excessive whitespace must hit the same limit.
	r := httptest.NewRequest("POST", "/api/v1/messages/sync", strings.NewReader(`{"messages":[]}`+strings.Repeat(" ", 3*1024*1024)))
	r.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	s.handler().ServeHTTP(w, r)
	if w.Code != 413 {
		t.Fatalf("oversized trailing data accepted: %d", w.Code)
	}
}

func TestSyncAcceptsMaximumContractBatch(t *testing.T) {
	for _, character := range []string{"短信", "😀", "\x00"} {
		t.Run(fmt.Sprintf("rune-%U", []rune(character)[0]), func(t *testing.T) {
			s, token := fixture(t)
			messages := make([]Message, 50)
			for i := range messages {
				m := testMessage()
				m.ID = fmt.Sprintf("maximum-message-%03d", i)
				m.Body = strings.Repeat(character, 4096/len([]rune(character)))
				m.Sender = strings.Repeat("😀", 64)
				m.Received += int64(i)
				messages[i] = m
			}
			w := call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": messages})
			if w.Code != 200 || len(s.store.Messages) != len(messages) {
				t.Fatalf("valid maximum batch rejected: status=%d stored=%d", w.Code, len(s.store.Messages))
			}
		})
	}
}

func TestSyncAcceptsMaximumSurrogateEscapedBatch(t *testing.T) {
	s, token := fixture(t)
	messages := make([]Message, 50)
	for i := range messages {
		m := testMessage()
		m.ID = fmt.Sprintf("surrogate-message-%03d", i)
		m.Body = strings.Repeat("😀", 4096)
		m.Sender = strings.Repeat("😀", 64)
		m.Received += int64(i)
		messages[i] = m
	}
	raw, err := json.Marshal(map[string]any{"messages": messages})
	if err != nil {
		t.Fatal(err)
	}
	// Some clients use ASCII-only JSON with two UTF-16 escapes per code point.
	escaped := strings.ReplaceAll(string(raw), "😀", `\ud83d\ude00`)
	r := httptest.NewRequest("POST", "/api/v1/messages/sync", strings.NewReader(escaped))
	r.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	s.handler().ServeHTTP(w, r)
	if w.Code != 200 || len(s.store.Messages) != len(messages) {
		t.Fatalf("valid surrogate-escaped batch rejected: status=%d stored=%d", w.Code, len(s.store.Messages))
	}
}

func TestMessageOperationReplayPreservesLaterIntentAfterRestart(t *testing.T) {
	for _, kind := range []string{"archive", "unarchive", "restore"} {
		t.Run(kind, func(t *testing.T) {
			s, token := fixture(t)
			m := testMessage()
			call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{m}})
			path := "/api/v1/messages/" + m.ID + "/"
			original := map[string]string{"operation_id": "original-operation-01"}
			if w := call(t, s, "POST", path+kind, token, original); w.Code != 200 {
				t.Fatal(w.Code, w.Body)
			}
			later := "archive"
			if kind == "archive" {
				later = "unarchive"
			}
			if w := call(t, s, "POST", path+later, token, map[string]string{"operation_id": "later-operation-0001"}); w.Code != 200 {
				t.Fatal(w.Code, w.Body)
			}
			before := s.store.Messages[m.ID]
			reopened, err := openStore(s.store.path)
			if err != nil {
				t.Fatal(err)
			}
			s = newServer(reopened, "")
			if w := call(t, s, "POST", path+kind, token, original); w.Code != 200 {
				t.Fatal(w.Code, w.Body)
			}
			after := s.store.Messages[m.ID]
			if before.Revision != after.Revision || before.Archived != after.Archived || before.Restored != after.Restored {
				t.Fatal("retry overwrote later intent", before, after)
			}
		})
	}
}

func TestMessageOperationIDConflictsAndFailedCommit(t *testing.T) {
	s, token := fixture(t)
	m, other := testMessage(), testMessage()
	other.ID = "other-message-0001"
	other.Received++
	call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{m, other}})
	op := map[string]string{"operation_id": "shared-operation-0001", "corrected_category": "service"}
	path := "/api/v1/messages/" + m.ID + "/"
	if w := call(t, s, "POST", path+"archive", token, op); w.Code != 200 {
		t.Fatal(w.Code, w.Body)
	}
	for _, target := range []string{path + "restore", path + "feedback", "/api/v1/messages/" + other.ID + "/archive"} {
		if w := call(t, s, "POST", target, token, op); w.Code != 409 {
			t.Fatalf("operation ID reused at %s: %d", target, w.Code)
		}
	}
	feedback := map[string]string{"operation_id": "feedback-operation-02", "corrected_category": "service"}
	if w := call(t, s, "POST", path+"feedback", token, feedback); w.Code != 200 {
		t.Fatal(w.Code, w.Body)
	}
	if w := call(t, s, "POST", path+"archive", token, feedback); w.Code != 409 {
		t.Fatal("feedback ID reused for archive", w.Code)
	}
	op = map[string]string{"operation_id": "failed-operation-0001"}
	goodPath := s.store.path
	s.store.path = filepath.Join(t.TempDir(), "missing", "store.enc")
	if w := call(t, s, "POST", path+"unarchive", token, op); w.Code != 503 {
		t.Fatal(w.Code, w.Body)
	}
	s.store.path = goodPath
	if !s.store.Messages[m.ID].Archived {
		t.Fatal("failed operation was not rolled back")
	}
	if w := call(t, s, "POST", path+"unarchive", token, op); w.Code != 200 || s.store.Messages[m.ID].Archived {
		t.Fatal("failed commit left a false receipt", w.Code, w.Body)
	}
}

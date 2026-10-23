package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func slowModel(t *testing.T, s *Server) (chan struct{}, chan struct{}) {
	t.Helper()
	entered, release := make(chan struct{}, 10), make(chan struct{})
	model := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/classify" {
			entered <- struct{}{}
			<-release
		}
		serveClassification(w, r, Classification{Category: "marketing", Confidence: .99, Risk: .99, Model: "synthetic", Review: true})
	}))
	s.classifier = model.URL
	t.Cleanup(model.Close)
	t.Cleanup(func() { close(release) })
	return entered, release
}
func awaitModel(t *testing.T, entered chan struct{}) {
	t.Helper()
	select {
	case <-entered:
	case <-time.After(3 * time.Second):
		t.Fatal("model did not start")
	}
}
func TestSlowClassificationDoesNotBlockReadsOrRevocation(t *testing.T) {
	s, token := fixture(t)
	entered, release := slowModel(t, s)
	done := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		done <- call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}})
	}()
	awaitModel(t, entered)
	read := make(chan int, 1)
	go func() { read <- call(t, s, "GET", "/api/v1/status", token, nil).Code }()
	select {
	case status := <-read:
		if status != 200 {
			t.Fatal(status)
		}
	case <-time.After(time.Second):
		t.Fatal("read blocked by model")
	}
	s.store.Devices["backup-admin-0001"] = Device{ID: "backup-admin-0001", Role: "admin", Active: true, Expires: time.Now().Add(time.Hour).Unix()}
	if w := call(t, s, "DELETE", "/api/v1/devices/test-device-0001", token, nil); w.Code != 200 {
		t.Fatal(w.Code)
	}
	release <- struct{}{}
	if w := <-done; w.Code != 401 {
		t.Fatal("revoked upload accepted", w.Code)
	}
	if len(s.store.Messages) != 0 {
		t.Fatal("revoked upload mutated store")
	}
}
func TestBackgroundClassificationPreservesConcurrentRestore(t *testing.T) {
	s, token := fixture(t)
	call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}})
	entered, release := slowModel(t, s)
	done := make(chan struct{})
	go func() { s.refreshClassifications(); close(done) }()
	awaitModel(t, entered)
	if w := call(t, s, "POST", "/api/v1/messages/"+testMessage().ID+"/restore", token, map[string]string{"operation_id": "concurrent-restore-0001"}); w.Code != 200 {
		t.Fatal(w.Code)
	}
	release <- struct{}{}
	<-done
	m := s.store.Messages[testMessage().ID]
	if !m.Restored || m.Classified || m.Reason != "用户恢复" {
		t.Fatal("stale model overwrote restored revision", m)
	}
}
func TestClassificationConfigChangeDiscardsInFlightResult(t *testing.T) {
	s, token := fixture(t)
	entered, release := slowModel(t, s)
	done := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		done <- call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}})
	}()
	awaitModel(t, entered)
	if w := call(t, s, "PUT", "/api/v1/filter/rules", token, Rules{Mode: "filter", Threshold: .9, Whitelist: []string{}, Blacklist: []string{}}); w.Code != 200 {
		t.Fatal(w.Code)
	}
	release <- struct{}{}
	if w := <-done; w.Code != 200 {
		t.Fatal(w.Code, w.Body)
	}
	if s.store.Messages[testMessage().ID].Classified {
		t.Fatal("accepted obsolete configuration result")
	}
}

func TestConflictingUploadRejectedBeforeModelCall(t *testing.T) {
	s, token := fixture(t)
	original := testMessage()
	original.Device = "test-device-0001"
	s.store.Messages[original.ID] = original
	requests := make(chan struct{}, 1)
	model := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { requests <- struct{}{}; w.WriteHeader(503) }))
	defer model.Close()
	s.classifier = model.URL
	conflicting := testMessage()
	conflicting.Body = "conflicting synthetic body"
	if w := call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{conflicting}}); w.Code != 409 {
		t.Fatal(w.Code)
	}
	select {
	case <-requests:
		t.Fatal("invalid upload reached model")
	default:
	}
}

func TestRetryRoundRobinAdvancesPastUnavailableMessage(t *testing.T) {
	s, _ := fixture(t)
	a, b := testMessage(), testMessage()
	a.ID = "message-A"
	a.Body = "A"
	b.ID = "message-B"
	b.Body = "B"
	s.store.Messages[a.ID] = a
	s.store.Messages[b.ID] = b
	model := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(503) }))
	defer model.Close()
	s.classifier = model.URL
	for _, want := range []string{a.ID, b.ID, a.ID} {
		s.refreshClassifications()
		if s.retryCursor != want {
			t.Fatal("retry starved later messages", s.retryCursor, want)
		}
	}
}

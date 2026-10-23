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
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func fixture(t *testing.T) (*Server, string) {
	t.Helper()
	store, err := openStore(filepath.Join(t.TempDir(), "store.enc"))
	if err != nil {
		t.Fatal(err)
	}
	s := newServer(store, "")
	token := "test-token"
	store.Devices["test-device-0001"] = Device{ID: "test-device-0001", Name: "test", Active: true, TokenHash: hash(token), Expires: time.Now().Add(time.Hour).Unix()}
	return s, token
}
func call(t *testing.T, s *Server, method, path, token string, body any) *httptest.ResponseRecorder {
	t.Helper()
	raw, _ := json.Marshal(body)
	r := httptest.NewRequest(method, path, bytes.NewReader(raw))
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	w := httptest.NewRecorder()
	s.handler().ServeHTTP(w, r)
	return w
}
func testMessage() Message {
	return Message{ID: "test-message-0001", Sender: "TEST", Body: "合成短信：周末优惠活动", Received: 1000, Subscription: 1, Slot: 0}
}
func TestPolicyProtection(t *testing.T) {
	r := Rules{Mode: "block", Threshold: 0.9, Blacklist: []string{"TEST"}}
	for _, category := range []string{"otp", "transaction", "uncertain"} {
		m := applyPolicy(testMessage(), Classification{Category: category, Confidence: 1, Calibrated: true, Model: "test"}, true, r)
		if m.Action != "allow" {
			t.Fatal(category)
		}
	}
	if applyPolicy(testMessage(), Classification{}, false, r).Action != "allow" {
		t.Fatal("fail open")
	}
	c := Classification{Category: "marketing", Confidence: 0.99, Review: true, Model: "preview"}
	if applyPolicy(testMessage(), c, true, Rules{Mode: "block", Threshold: 0.9}).Action != "allow" {
		t.Fatal("uncalibrated")
	}
	if applyPolicy(testMessage(), c, true, r).Action != "quarantine" {
		t.Fatal("explicit blacklist")
	}
	r.Whitelist = []string{"TEST"}
	if applyPolicy(testMessage(), c, true, r).Action != "allow" {
		t.Fatal("whitelist")
	}
}
func TestAuthAndDurableIdempotency(t *testing.T) {
	s, token := fixture(t)
	body := map[string]any{"messages": []Message{testMessage()}}
	if call(t, s, "POST", "/api/v1/messages/sync", "", body).Code != 401 {
		t.Fatal("auth missing")
	}
	for i := 0; i < 2; i++ {
		if w := call(t, s, "POST", "/api/v1/messages/sync", token, body); w.Code != 200 {
			t.Fatal(w.Code, w.Body)
		}
	}
	if len(s.store.Messages) != 1 {
		t.Fatal("duplicate")
	}
	m := s.store.Messages[testMessage().ID]
	if m.Action != "allow" || m.Category != "uncertain" {
		t.Fatal("fail open")
	}
	restored, err := openStore(s.store.path)
	if err != nil || len(restored.Messages) != 1 {
		t.Fatal("not durable", err)
	}
	raw, _ := os.ReadFile(s.store.path)
	if bytes.Contains(raw, []byte(testMessage().Body)) || bytes.Contains(raw, []byte(token)) {
		t.Fatal("plaintext at rest")
	}
	conflict := testMessage()
	conflict.Body = "another body"
	if call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{conflict}}).Code != 409 {
		t.Fatal("conflicting id")
	}
}
func TestClassifierRestoreFeedbackCursorAndRevoke(t *testing.T) {
	s, token := fixture(t)
	classifier := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		serveClassification(w, r, Classification{Category: "marketing", Confidence: 0.99, Risk: 0.99, Review: true, Model: "test-preview"})
	}))
	defer classifier.Close()
	s.classifier = classifier.URL
	rules := Rules{Mode: "block", Threshold: 0.95, Blacklist: []string{"TEST"}}
	if call(t, s, "PUT", "/api/v1/filter/rules", token, rules).Code != 200 {
		t.Fatal("rules")
	}
	if call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}}).Code != 200 {
		t.Fatal("sync")
	}
	if s.store.Messages[testMessage().ID].Action != "quarantine" {
		t.Fatal("quarantine")
	}
	w := call(t, s, "GET", "/api/v1/messages?cursor=0&limit=1", token, nil)
	if w.Code != 200 || !strings.Contains(w.Body.String(), "test-preview") {
		t.Fatal("query")
	}
	path := "/api/v1/messages/" + testMessage().ID
	if call(t, s, "POST", path+"/restore", token, map[string]string{"operation_id": "restore-operation-01"}).Code != 200 {
		t.Fatal("restore")
	}
	for i := 0; i < 2; i++ {
		if call(t, s, "POST", path+"/feedback", token, map[string]string{"operation_id": "feedback-operation-01", "corrected_category": "service"}).Code != 200 {
			t.Fatal("feedback")
		}
	}
	if len(s.store.Feedback) != 1 || s.store.Messages[testMessage().ID].Category != "marketing" {
		t.Fatal("feedback must not relabel predictions")
	}
	s.store.Devices["backup-admin-0001"] = Device{ID: "backup-admin-0001", Role: "admin", Active: true, Expires: time.Now().Add(time.Hour).Unix()}
	if call(t, s, "DELETE", "/api/v1/devices/test-device-0001", token, nil).Code != 200 {
		t.Fatal("revoke")
	}
	if call(t, s, "GET", "/api/v1/messages", token, nil).Code != 401 {
		t.Fatal("revoked token")
	}
}
func TestSignedSingleUsePairing(t *testing.T) {
	s, _ := fixture(t)
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	der, _ := x509.MarshalPKIXPublicKey(&key.PublicKey)
	encoded := base64.StdEncoding.EncodeToString(der)
	id, nonce := "signed-device-0001", "nonce-with-enough-entropy"
	code := s.code
	digest := sha256.Sum256([]byte(id + "\n" + encoded + "\n" + nonce + "\n" + code))
	sig, _ := ecdsa.SignASN1(rand.Reader, key, digest[:])
	req := map[string]string{"device_id": id, "name": "test", "public_key": encoded, "nonce": nonce, "pairing_code": code, "signature": base64.StdEncoding.EncodeToString(sig)}
	if w := call(t, s, "POST", "/api/v1/devices/register", "", req); w.Code != 201 {
		t.Fatal(w.Code, w.Body)
	}
	if call(t, s, "POST", "/api/v1/devices/register", "", req).Code != 403 {
		t.Fatal("pair replay")
	}
}
func TestFailedCommitDoesNotAcknowledge(t *testing.T) {
	s, token := fixture(t)
	s.store.path = filepath.Join(t.TempDir(), "missing", "store.enc")
	w := call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}})
	if w.Code != 503 || len(s.store.Messages) != 0 {
		t.Fatal("commit rollback", w.Code)
	}
}
func TestClassificationOutageEventuallyRecoversAfterAck(t *testing.T) {
	s, token := fixture(t)
	call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}})
	if s.store.Messages[testMessage().ID].Classified {
		t.Fatal("outage incorrectly classified")
	}
	classifier := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		serveClassification(w, r, Classification{Category: "marketing", Confidence: 0.99, Review: true, Model: "recovered-model"})
	}))
	defer classifier.Close()
	s.classifier = classifier.URL
	s.refreshClassifications()
	m := s.store.Messages[testMessage().ID]
	if !m.Classified || m.Model != "recovered-model" || m.Revision <= 1 {
		t.Fatal("recovery did not advance cursor")
	}
}
func TestMalformedClassifierIsFailOpen(t *testing.T) {
	s, _ := fixture(t)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"category":"marketing","confidence":0.99,"spam_score":0.99,"confidence_calibrated":true,"model_version":"missing-review"}`))
	}))
	defer upstream.Close()
	s.classifier = upstream.URL
	if _, ok := s.classify(testMessage()); ok {
		t.Fatal("missing review metadata must not be trusted")
	}
}

// Fixture implements both official endpoints. Production never derives decisions locally.
func serveClassification(w http.ResponseWriter, r *http.Request, c Classification) {
	if r.URL.Path == "/api/v1/classify" {
		writeJSON(w, 200, c)
		return
	}
	if r.URL.Path != "/sms/score" {
		http.NotFound(w, r)
		return
	}
	action := "allow"
	if c.IsSpam && c.Calibrated && !c.Review && (c.Category == "marketing" || c.Category == "suspicious") {
		action = "block"
	}
	writeJSON(w, 200, ScoreDecision{Action: action, Score: c.Risk, Reason: "upstream-fixture", Model: c.Model, Threshold: 0.5, Category: c.Category, Review: c.Review})
}

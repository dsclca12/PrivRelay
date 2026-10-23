package main

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func TestAndroidSharedMessageContract(t *testing.T) {
	s, token := fixture(t)
	w := call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}})
	if w.Code != 200 {
		t.Fatal(w.Code, w.Body)
	}
	var response struct {
		Messages []map[string]any `json:"messages"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join("..", "contracts", "message.json"))
	if err != nil {
		t.Fatal(err)
	}
	var expected map[string]any
	if err := json.Unmarshal(raw, &expected); err != nil {
		t.Fatal(err)
	}
	if len(response.Messages) != 1 || !reflect.DeepEqual(response.Messages[0], expected) {
		t.Fatalf("Android message contract drift: %s", w.Body)
	}
}

func TestCancelledClassificationStillDurablyAcknowledgesBatch(t *testing.T) {
	s, token := fixture(t)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body)
		<-r.Context().Done()
	}))
	defer upstream.Close()
	s.classifier = upstream.URL
	messages := make([]Message, 50)
	for i := range messages {
		messages[i] = testMessage()
		messages[i].ID = fmt.Sprintf("budget-message-%04d", i)
		messages[i].Received += int64(i)
	}
	raw, _ := json.Marshal(map[string]any{"messages": messages})
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	r := httptest.NewRequest("POST", "/api/v1/messages/sync", bytes.NewReader(raw)).WithContext(ctx)
	r.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	start := time.Now()
	s.handler().ServeHTTP(w, r)
	if w.Code != 200 || time.Since(start) > 2*time.Second || len(s.store.Messages) != 50 {
		t.Fatalf("failed bounded fail-open: %d, %s", w.Code, time.Since(start))
	}
	reopened, err := openStore(s.store.path)
	if err != nil || len(reopened.Messages) != 50 {
		t.Fatal("batch was not durable", err)
	}
	for _, m := range reopened.Messages {
		if m.Classified || m.Action != "allow" {
			t.Fatal("cancelled classifier caused message loss or quarantine")
		}
	}
}

func browserCall(s *Server, method, path, origin, token string, cookie *http.Cookie, body any) *httptest.ResponseRecorder {
	raw, _ := json.Marshal(body)
	r := httptest.NewRequest(method, "http://relay.test"+path, bytes.NewReader(raw))
	if origin != "" {
		r.Header.Set("Origin", origin)
	}
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	if cookie != nil {
		r.AddCookie(cookie)
	}
	w := httptest.NewRecorder()
	s.handler().ServeHTTP(w, r)
	return w
}

func signedRegistration(t *testing.T, id, code string) map[string]string {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	der, _ := x509.MarshalPKIXPublicKey(&key.PublicKey)
	public := base64.StdEncoding.EncodeToString(der)
	nonce := randomToken()
	digest := sha256.Sum256([]byte(id + "\n" + public + "\n" + nonce + "\n" + code))
	sig, _ := ecdsa.SignASN1(rand.Reader, key, digest[:])
	return map[string]string{"device_id": id, "name": "Android contract fixture", "public_key": public, "nonce": nonce, "pairing_code": code, "signature": base64.StdEncoding.EncodeToString(sig)}
}

func TestBrowserSessionCSRFAndRevocation(t *testing.T) {
	s, token := fixture(t)
	for _, origin := range []string{"", "http://evil.test", "null"} {
		if w := browserCall(s, "POST", "/api/v1/session", origin, token, nil, nil); w.Code != 403 {
			t.Fatalf("origin %q: %d", origin, w.Code)
		}
	}
	w := browserCall(s, "POST", "/api/v1/session", "http://relay.test", token, nil, nil)
	if w.Code != 200 {
		t.Fatal(w.Code, w.Body)
	}
	cookies := w.Result().Cookies()
	if len(cookies) != 1 || !cookies[0].HttpOnly || cookies[0].SameSite != http.SameSiteStrictMode || cookies[0].Path != "/api/v1" {
		t.Fatal("unsafe cookie")
	}
	cookie := cookies[0]
	if w := browserCall(s, "GET", "/api/v1/session", "", "", cookie, nil); w.Code != 200 {
		t.Fatal(w.Code)
	}
	for _, origin := range []string{"", "http://evil.test"} {
		if w := browserCall(s, "POST", "/api/v1/pairing-codes", origin, "", cookie, nil); w.Code != 401 {
			t.Fatal("CSRF accepted", origin, w.Code)
		}
	}
	if w := browserCall(s, "POST", "/api/v1/pairing-codes", "http://relay.test", "", cookie, nil); w.Code != 201 {
		t.Fatal(w.Code)
	}
	// Native bearer requests do not need a browser Origin.
	if w := call(t, s, "POST", "/api/v1/pairing-codes", token, nil); w.Code != 201 {
		t.Fatal(w.Code)
	}
	if w := browserCall(s, "DELETE", "/api/v1/session", "http://relay.test", "", cookie, nil); w.Code != 200 || w.Result().Cookies()[0].MaxAge != -1 {
		t.Fatal("logout")
	}
	s.store.Devices["backup-admin-0001"] = Device{ID: "backup-admin-0001", Role: "admin", Active: true, Expires: time.Now().Add(time.Hour).Unix()}
	call(t, s, "DELETE", "/api/v1/devices/test-device-0001", token, nil)
	if w := browserCall(s, "GET", "/api/v1/messages", "", "", cookie, nil); w.Code != 401 {
		t.Fatal("revoked cookie accepted")
	}
}

func TestWebPairingCodeWorksWithAndroidSignatureAndSingleUse(t *testing.T) {
	s, token := fixture(t)
	old := s.code
	w := call(t, s, "POST", "/api/v1/pairing-codes", token, nil)
	var code struct {
		Code    string `json:"pairing_code"`
		Expires int64  `json:"expires_at"`
	}
	json.Unmarshal(w.Body.Bytes(), &code)
	if w.Code != 201 || code.Code == "" || code.Code == old || code.Expires <= time.Now().Unix() {
		t.Fatal("code", w.Body)
	}
	if w := call(t, s, "GET", "/api/v1/pairing-codes", "", nil); w.Code != 401 {
		t.Fatal("pairing status exposed without authentication")
	}
	status := call(t, s, "GET", "/api/v1/pairing-codes", token, nil)
	if status.Code != 200 || !strings.Contains(status.Body.String(), `"active":true`) || strings.Contains(status.Body.String(), code.Code) {
		t.Fatal("pairing status invalid or exposes secret", status.Body)
	}
	if w := call(t, s, "POST", "/api/v1/devices/register", "", signedRegistration(t, "old-code-device-01", old)); w.Code != 403 {
		t.Fatal("old code accepted")
	}
	req := signedRegistration(t, "android-device-01", code.Code)
	w = call(t, s, "POST", "/api/v1/devices/register", "", req)
	var registered struct {
		Token string `json:"token"`
	}
	json.Unmarshal(w.Body.Bytes(), &registered)
	if w.Code != 201 || registered.Token == "" {
		t.Fatal(w.Code, w.Body)
	}
	status = call(t, s, "GET", "/api/v1/pairing-codes", token, nil)
	if !strings.Contains(status.Body.String(), `"active":false`) {
		t.Fatal("consumed code remains active", status.Body)
	}
	if w := call(t, s, "POST", "/api/v1/devices/register", "", req); w.Code != 403 {
		t.Fatal("replayed code accepted")
	}
	m := testMessage()
	if w := call(t, s, "POST", "/api/v1/messages/sync", registered.Token, map[string]any{"messages": []Message{m}}); w.Code != 200 {
		t.Fatal(w.Code)
	}
	if s.store.Messages[m.ID].Device != "android-device-01" {
		t.Fatal("wrong identity")
	}
	if w := call(t, s, "GET", "/api/v1/messages/"+m.ID, token, nil); w.Code != 200 || !strings.Contains(w.Body.String(), "android-device-01") {
		t.Fatal("web cannot see phone upload")
	}
}

func TestSearchQuarantineAndSyncHaveIndependentPagination(t *testing.T) {
	s, token := fixture(t)
	for i, id := range []string{"message-00000001", "message-00000002", "message-00000003"} {
		m := testMessage()
		m.ID = id
		m.Received = int64(100 + i)
		m.Category = "marketing"
		m.Revision = int64(i + 1)
		if i == 1 {
			m.Action = "quarantine"
		} else {
			m.Action = "allow"
		}
		s.store.Messages[id] = m
	}
	var page struct {
		Messages []Message `json:"messages"`
		Total    int       `json:"total"`
		More     bool      `json:"has_more"`
	}
	w := call(t, s, "GET", "/api/v1/messages/search?limit=1&category=marketing&q=TEST", token, nil)
	json.Unmarshal(w.Body.Bytes(), &page)
	if w.Code != 200 || page.Total != 3 || !page.More || page.Messages[0].ID != "message-00000003" {
		t.Fatal(w.Body)
	}
	w = call(t, s, "GET", "/api/v1/filter/quarantine", token, nil)
	json.Unmarshal(w.Body.Bytes(), &page)
	if page.Total != 1 || page.Messages[0].ID != "message-00000002" {
		t.Fatal(w.Body)
	}
	for _, q := range []string{"limit=51", "offset=-1", "offset=oops", "category=invalid", "action=delete"} {
		if w := call(t, s, "GET", "/api/v1/messages/search?"+q, token, nil); w.Code != 400 {
			t.Fatal(q, w.Code)
		}
	}
	w = call(t, s, "GET", "/api/v1/messages?cursor=0&limit=1", token, nil)
	json.Unmarshal(w.Body.Bytes(), &page)
	if page.Messages[0].ID != "message-00000001" {
		t.Fatal("sync no longer uses ascending revision")
	}
	if w := call(t, s, "GET", "/api/v1/messages/missing", token, nil); w.Code != 404 {
		t.Fatal(w.Code)
	}
	if w := call(t, s, "GET", "/api/v1/status", token, nil); w.Code != 200 || strings.Contains(w.Body.String(), testMessage().Body) {
		t.Fatal("status leaks messages")
	}
}

func TestBrowserAndAndroidWebSocketsAndExpiredSessions(t *testing.T) {
	s, token := fixture(t)
	ts := httptest.NewServer(s.handler())
	defer ts.Close()
	wsURL := "ws" + strings.TrimPrefix(ts.URL, "http") + "/api/v1/ws"
	headers := http.Header{"Authorization": []string{"Bearer " + token}}
	phone, _, err := websocket.DefaultDialer.Dial(wsURL, headers)
	if err != nil {
		t.Fatal(err)
	}
	defer phone.Close()
	headers = http.Header{"Origin": []string{ts.URL}, "Cookie": []string{"privrelay_session=" + token}}
	web, _, err := websocket.DefaultDialer.Dial(wsURL, headers)
	if err != nil {
		t.Fatal(err)
	}
	defer web.Close()
	headers.Set("Origin", "https://evil.test")
	if rejected, response, err := websocket.DefaultDialer.Dial(wsURL, headers); err == nil {
		rejected.Close()
		t.Fatal("cross-origin socket accepted")
	} else if response != nil {
		response.Body.Close()
	}
	call(t, s, "PUT", "/api/v1/filter/rules", token, Rules{Mode: "classify", Threshold: 0.95})
	for _, c := range []*websocket.Conn{phone, web} {
		c.SetReadDeadline(time.Now().Add(2 * time.Second))
		var event map[string]string
		if err := c.ReadJSON(&event); err != nil || event["event"] != "changed" {
			t.Fatal(event, err)
		}
	}
	// Verify an encrypted relay to a distinct paired device is volatile.
	secondToken := "synthetic-second-device-token"
	s.mu.Lock()
	s.store.Devices["test-device-0002"] = Device{ID: "test-device-0002", TokenHash: hash(secondToken), Active: true, Expires: time.Now().Add(time.Hour).Unix()}
	revision := s.store.Revision
	s.mu.Unlock()
	targetHeaders := http.Header{"Authorization": []string{"Bearer " + secondToken}}
	target, _, err := websocket.DefaultDialer.Dial(wsURL, targetHeaders)
	if err != nil {
		t.Fatal("second device websocket", err)
	}
	defer target.Close()
	if err := phone.WriteJSON(map[string]any{"event": "sms_relay", "body": "synthetic-should-be-stripped", "message": map[string]string{"message_id": "volatile-001", "ciphertext": "synthetic-client-encrypted-frame", "body": "synthetic-should-be-stripped"}}); err != nil {
		t.Fatal("relay write", err)
	}
	target.SetReadDeadline(time.Now().Add(2 * time.Second))
	var relay map[string]any
	if err := target.ReadJSON(&relay); err != nil || relay["event"] != "sms_relay" || relay["body"] != nil {
		t.Fatal("relay was not forwarded", relay, err)
	}
	message, ok := relay["message"].(map[string]any)
	if !ok || len(message) != 2 {
		t.Fatal("server forwarded fields outside the encrypted envelope", relay)
	}
	s.mu.Lock()
	_, persisted := s.store.EncryptedMessages["volatile-001"]
	unchanged := s.store.Revision == revision
	delete(s.store.Devices, "test-device-0002")
	s.mu.Unlock()
	if persisted || !unchanged {
		t.Fatal("volatile relay was persisted")
	}
	s.mu.Lock()
	d := s.store.Devices["test-device-0001"]
	d.Expires = time.Now().Add(-time.Second).Unix()
	s.store.Devices[d.ID] = d
	s.broadcast()
	s.mu.Unlock()
	if _, _, err := web.ReadMessage(); err == nil {
		t.Fatal("expired websocket remains authorized")
	}
}

func TestOptionalStaticHostingDoesNotExposeServerData(t *testing.T) {
	s, _ := fixture(t)
	dir := t.TempDir()
	s.webDir = filepath.Join(dir, "dist")
	os.Mkdir(s.webDir, 0700)
	os.WriteFile(filepath.Join(s.webDir, "index.html"), []byte("<html>frontend owned elsewhere</html>"), 0600)
	os.WriteFile(filepath.Join(dir, "secret.key"), []byte("do-not-serve"), 0600)
	for _, path := range []string{"/../secret.key", "/api/unknown", "/main.go"} {
		w := call(t, s, "GET", path, "", nil)
		body, _ := io.ReadAll(w.Result().Body)
		if strings.Contains(string(body), "do-not-serve") || w.Code == 200 {
			t.Fatal(path, w.Code)
		}
	}
	if w := call(t, s, "GET", "/", "", nil); w.Code != 200 || w.Header().Get("Content-Security-Policy") == "" {
		t.Fatal(w.Code)
	}
}

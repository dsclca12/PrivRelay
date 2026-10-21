package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

func llmReply(w http.ResponseWriter, content string, finish string) {
	writeJSON(w, 200, map[string]any{"choices": []any{map[string]any{"finish_reason": finish, "message": map[string]string{"content": content}}}})
}

const marketingJSON = `{"category":"marketing","confidence":0.99,"spam_score":0.99,"needs_review":false,"reason":"promotional"}`

func TestLLMSettingsAuthDurabilityAndSecretHandling(t *testing.T) {
	s, token := fixture(t)
	if w := call(t, s, "GET", "/api/v1/ai/settings", "", nil); w.Code != 401 {
		t.Fatal("unauthenticated configuration")
	}
	empty := call(t, s, "GET", "/api/v1/ai/settings", token, nil)
	if !strings.Contains(empty.Body.String(), `"base_url":""`) || !strings.Contains(empty.Body.String(), `"mode":"disabled"`) {
		t.Fatal(empty.Body)
	}
	cfg := LLMSettings{Mode: "primary", BaseURL: "https://model.example/v1", Model: "test", Key: "synthetic-secret", Threshold: 0.95}
	w := call(t, s, "PUT", "/api/v1/ai/settings", token, cfg)
	if w.Code != 200 || strings.Contains(w.Body.String(), cfg.Key) {
		t.Fatal(w.Code, w.Body)
	}
	raw, _ := os.ReadFile(s.store.path)
	if bytes.Contains(raw, []byte(cfg.Key)) {
		t.Fatal("plaintext secret")
	}
	reopened, err := openStore(s.store.path)
	if err != nil || reopened.LLM.Key != cfg.Key {
		t.Fatal("key not durable", err)
	}
	cfg.Key = ""
	call(t, s, "PUT", "/api/v1/ai/settings", token, cfg)
	if s.store.LLM.Key != "synthetic-secret" {
		t.Fatal("blank key erased credential")
	}
	cfg.BaseURL = "https://other.example/v1"
	call(t, s, "PUT", "/api/v1/ai/settings", token, cfg)
	if s.store.LLM.Key != "" {
		t.Fatal("key crossed destinations")
	}
	cfg.BaseURL = "http://127.0.0.1:123/v1"
	if call(t, s, "PUT", "/api/v1/ai/settings", token, cfg).Code != 422 {
		t.Fatal("HTTP accepted without opt in")
	}
	cfg.AllowHTTP = true
	if call(t, s, "PUT", "/api/v1/ai/settings", token, cfg).Code != 200 {
		t.Fatal("explicit HTTP rejected")
	}
	cfg.BaseURL = "https://user:secret@example.com/v1"
	if call(t, s, "PUT", "/api/v1/ai/settings", token, cfg).Code != 422 {
		t.Fatal("embedded credential")
	}
	before := s.store.LLM
	s.store.path = t.TempDir()
	cfg.BaseURL = "https://valid.example/v1"
	if call(t, s, "PUT", "/api/v1/ai/settings", token, cfg).Code != 503 || s.store.LLM != before {
		t.Fatal("storage rollback")
	}
}
func TestLLMClassificationAndPolicyMatrix(t *testing.T) {
	for _, tc := range []struct {
		name, content, finish, body, category string
		authorize, review, restored, white    bool
		want                                  string
		valid                                 bool
	}{
		{name: "explicit_block", content: marketingJSON, authorize: true, want: "quarantine", valid: true},
		{name: "classify_by_default", content: marketingJSON, want: "allow", valid: true},
		{name: "otp_content", content: marketingJSON, body: "您的验证码123456", authorize: true, want: "allow", valid: true},
		{name: "transaction_content", content: marketingJSON, body: "账户扣款通知", authorize: true, want: "allow", valid: true},
		{name: "restore", content: marketingJSON, authorize: true, restored: true, want: "allow", valid: true},
		{name: "whitelist", content: marketingJSON, authorize: true, white: true, want: "allow", valid: true},
		{name: "review", content: strings.Replace(marketingJSON, `false`, `true`, 1), authorize: true, want: "allow", valid: true},
		{name: "low_confidence", content: strings.ReplaceAll(marketingJSON, `0.99`, `0.85`), authorize: true, want: "allow", valid: true},
		{name: "uncertain", content: strings.Replace(marketingJSON, `marketing`, `uncertain`, 1), authorize: true, want: "allow", valid: true},
		{name: "otp_category", content: strings.Replace(marketingJSON, `marketing`, `otp`, 1), authorize: true, want: "allow", valid: true},
		{name: "malformed", content: `not JSON`, authorize: true, want: "allow"},
		{name: "missing_review", content: `{"category":"marketing","confidence":1,"spam_score":1,"reason":"test"}`, authorize: true, want: "allow"},
		{name: "null_review", content: strings.Replace(marketingJSON, `false`, `null`, 1), authorize: true, want: "allow"},
		{name: "invalid_score", content: strings.ReplaceAll(marketingJSON, `0.99`, `1.5`), authorize: true, want: "allow"},
		{name: "unknown_category", content: strings.Replace(marketingJSON, `marketing`, `delete`, 1), authorize: true, want: "allow"},
		{name: "truncated", content: marketingJSON, finish: "length", authorize: true, want: "allow"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s, _ := fixture(t)
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/v1/chat/completions" || r.Header.Get("Authorization") != "Bearer synthetic" {
					t.Error("request contract")
				}
				var request map[string]any
				if json.NewDecoder(r.Body).Decode(&request) != nil || request["model"] != "test" {
					t.Error("model request")
				}
				finish := tc.finish
				if finish == "" {
					finish = "stop"
				}
				llmReply(w, tc.content, finish)
			}))
			defer upstream.Close()
			s.store.LLM = LLMSettings{Mode: "primary", BaseURL: upstream.URL + "/v1", Model: "test", Key: "synthetic", AutoQuarantine: tc.authorize, Threshold: 0.95}
			m := testMessage()
			m.Restored = tc.restored
			if tc.body != "" {
				m.Body = tc.body
			}
			c, ok := s.classify(m)
			if ok != tc.valid {
				t.Fatalf("valid=%v", ok)
			}
			rules := Rules{Mode: "block"}
			if tc.white {
				rules.Whitelist = []string{m.Sender}
			}
			result := applyPolicy(m, c, ok, rules)
			if result.Action != tc.want {
				t.Fatal(result.Action)
			}
			if ok && (result.Source != "llm" || result.Model != "llm:test" || result.ClassifierThreshold == nil) {
				t.Fatal("missing provenance")
			}
		})
	}
}
func TestLLMFaultsAndFallbackRetry(t *testing.T) {
	s, token := fixture(t)
	var fail = true
	llm := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if fail {
			w.WriteHeader(503)
			return
		}
		llmReply(w, marketingJSON, "stop")
	}))
	defer llm.Close()
	primary := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		serveClassification(w, r, Classification{Category: "marketing", Confidence: 0.99, Risk: 0.99, Review: true, Model: "preview"})
	}))
	defer primary.Close()
	s.classifier = primary.URL
	s.store.LLM = LLMSettings{Mode: "fallback", BaseURL: llm.URL, Model: "test", AutoQuarantine: true, Threshold: 0.95}
	s.store.Rules.Mode = "block"
	w := call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}})
	if w.Code != 200 {
		t.Fatal(w.Code)
	}
	m := s.store.Messages[testMessage().ID]
	if !m.Classified || !m.LLMPending || m.Action != "allow" || m.Model != "preview" {
		t.Fatal(m)
	}
	fail = false
	s.refreshClassifications()
	m = s.store.Messages[m.ID]
	if m.Action != "quarantine" || m.LLMPending || m.Source != "llm" || m.PrimaryClassification == nil || m.PrimaryClassification.Model != "preview" {
		t.Fatal(m)
	}
	restored := call(t, s, "POST", "/api/v1/messages/"+m.ID+"/restore", token, map[string]string{"operation_id": "llm-restore-test-0001"})
	if restored.Code != 200 {
		t.Fatal(restored.Code)
	}
	call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}})
	if s.store.Messages[m.ID].Action != "allow" {
		t.Fatal("replay lost restoration")
	}
	ctx, cancel := context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer cancel()
	if _, ok := s.classifyLLM(ctx, testMessage()); ok {
		t.Fatal("expired context accepted")
	}
}

func TestLLMOutageACKAndSyntheticProbe(t *testing.T) {
	for _, fault := range []string{"unavailable", "invalid_json", "redirect"} {
		t.Run(fault, func(t *testing.T) {
			s, token := fixture(t)
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch fault {
				case "unavailable":
					w.WriteHeader(503)
				case "invalid_json":
					llmReply(w, `{"category":"marketing"}`, "stop")
				case "redirect":
					http.Redirect(w, r, "https://other.invalid", 302)
				}
			}))
			defer upstream.Close()
			s.store.LLM = LLMSettings{Mode: "primary", BaseURL: upstream.URL, Model: "test", AutoQuarantine: true}
			s.store.Rules.Mode = "block"
			for i := 0; i < 2; i++ {
				if call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}}).Code != 200 {
					t.Fatal("failed ACK")
				}
			}
			reopened, err := openStore(s.store.path)
			if err != nil {
				t.Fatal(err)
			}
			m := reopened.Messages[testMessage().ID]
			if len(reopened.Messages) != 1 || m.Classified || m.Action != "allow" || m.Body != testMessage().Body {
				t.Fatal("lost or isolated data")
			}
			if call(t, s, "POST", "/api/v1/ai/test", "", nil).Code != 401 {
				t.Fatal("probe auth")
			}
			if call(t, s, "POST", "/api/v1/ai/test", token, nil).Code != 502 {
				t.Fatal("probe should fail")
			}
		})
	}
	s, token := fixture(t)
	mock := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { llmReply(w, marketingJSON, "stop") }))
	defer mock.Close()
	s.store.LLM = LLMSettings{BaseURL: mock.URL, Model: "test"}
	if call(t, s, "POST", "/api/v1/ai/test", token, nil).Code != 200 || len(s.store.Messages) != 0 {
		t.Fatal("synthetic probe persisted a message")
	}
}

func TestLLMClearKeyAndUnchangedFallback(t *testing.T) {
	s, token := fixture(t)
	s.store.LLM = LLMSettings{Mode: "disabled", Key: "synthetic-secret"}
	w := call(t, s, "PUT", "/api/v1/ai/settings", token, map[string]any{"mode": "disabled", "clear_api_key": true})
	if w.Code != 200 || s.store.LLM.Key != "" {
		t.Fatal("explicit key removal failed")
	}
}

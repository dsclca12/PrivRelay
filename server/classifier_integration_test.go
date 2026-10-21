package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func classifierFixture() (map[string]any, map[string]any) {
	return map[string]any{"category": "marketing", "confidence": 0.99, "spam_score": 0.9, "is_spam": true,
			"needs_review": false, "confidence_calibrated": true, "model_version": "upstream-test"},
		map[string]any{"action": "block", "category": "marketing", "score": 0.9, "reason": "risk_category:marketing",
			"needsReview": false, "modelVersion": "upstream-test", "thresholdUsed": 0.5}
}

func TestUpstreamDecisionContractMatrix(t *testing.T) {
	tests := []struct {
		name   string
		change func(map[string]any, map[string]any)
		valid  bool
		action string
	}{
		{"block_authority", nil, true, "quarantine"},
		{"allow_authority_despite_high_confidence", func(c, d map[string]any) { d["action"] = "allow" }, true, "allow"},
		{"upstream_threshold_used_instead_of_local_threshold", func(c, d map[string]any) { c["spam_score"], d["score"] = 0.6, 0.6 }, true, "quarantine"},
		{"preview_review_allowed", func(c, d map[string]any) {
			c["confidence_calibrated"], c["needs_review"] = false, true
			d["needsReview"], d["action"] = true, "allow"
		}, true, "allow"},
		{"null_review", func(c, d map[string]any) { c["needs_review"] = nil }, false, "allow"},
		{"missing_review", func(c, d map[string]any) { delete(d, "needsReview") }, false, "allow"},
		{"missing_spam_flag", func(c, d map[string]any) { delete(c, "is_spam") }, false, "allow"},
		{"invalid_confidence", func(c, d map[string]any) { c["confidence"] = 1.1 }, false, "allow"},
		{"negative_risk", func(c, d map[string]any) { c["spam_score"] = -1 }, false, "allow"},
		{"string_probability", func(c, d map[string]any) { c["confidence"] = "0.99" }, false, "allow"},
		{"unknown_category", func(c, d map[string]any) { c["category"] = "spam" }, false, "allow"},
		{"empty_model", func(c, d map[string]any) { c["model_version"] = "" }, false, "allow"},
		{"long_model", func(c, d map[string]any) { c["model_version"] = strings.Repeat("m", 101) }, false, "allow"},
		{"model_changed_between_requests", func(c, d map[string]any) { d["modelVersion"] = "other-model" }, false, "allow"},
		{"category_changed_between_requests", func(c, d map[string]any) { d["category"] = "service" }, false, "allow"},
		{"risk_changed_between_requests", func(c, d map[string]any) { d["score"] = 0.8 }, false, "allow"},
		{"review_changed_between_requests", func(c, d map[string]any) { d["needsReview"] = true }, false, "allow"},
		{"unknown_action", func(c, d map[string]any) { d["action"] = "delete" }, false, "allow"},
		{"invalid_threshold", func(c, d map[string]any) { d["thresholdUsed"] = 2 }, false, "allow"},
		{"empty_reason", func(c, d map[string]any) { d["reason"] = "" }, false, "allow"},
		{"review_cannot_block", func(c, d map[string]any) { c["needs_review"], d["needsReview"] = true, true }, false, "allow"},
		{"uncalibrated_cannot_block", func(c, d map[string]any) { c["confidence_calibrated"] = false }, false, "allow"},
		{"not_spam_cannot_block", func(c, d map[string]any) { c["is_spam"] = false }, false, "allow"},
		{"otp_cannot_block", func(c, d map[string]any) { c["category"], d["category"] = "otp", "otp" }, false, "allow"},
		{"transaction_cannot_block", func(c, d map[string]any) { c["category"], d["category"] = "transaction", "transaction" }, false, "allow"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			c, d := classifierFixture()
			if test.change != nil {
				test.change(c, d)
			}
			s, _ := fixture(t)
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("X-API-Key") != "fixture-key" {
					t.Error("API key not forwarded")
				}
				var payload map[string]any
				if json.NewDecoder(r.Body).Decode(&payload) != nil {
					t.Error("invalid request JSON")
				}
				switch r.URL.Path {
				case "/api/v1/classify":
					if payload["text"] != testMessage().Body || payload["sender"] != "TEST" {
						t.Error("wrong classification input")
					}
					writeJSON(w, 200, c)
				case "/sms/score":
					if payload["body"] != testMessage().Body || payload["timestamp"] != float64(testMessage().Received) || payload["profile"] != "conservative" || payload["modelVersion"] != "upstream-test" {
						t.Error("wrong score input")
					}
					writeJSON(w, 200, d)
				default:
					t.Error("wrong upstream route")
					http.NotFound(w, r)
				}
			}))
			defer upstream.Close()
			s.classifier, s.classifierKey = upstream.URL, "fixture-key"
			classification, ok := s.classify(testMessage())
			if ok != test.valid {
				t.Fatalf("valid=%v expected=%v", ok, test.valid)
			}
			m := applyPolicy(testMessage(), classification, ok, Rules{Mode: "block", Threshold: 0.99})
			if m.Action != test.action {
				t.Fatalf("action=%s expected=%s", m.Action, test.action)
			}
			if ok && (m.ClassifierAction == "" || m.ClassifierThreshold == nil || *m.ClassifierThreshold != 0.5) {
				t.Fatal("decision provenance not preserved")
			}
		})
	}
}

func TestUpstreamTransportFaultsAreDurableFailOpen(t *testing.T) {
	for _, fault := range []string{"classify_401", "score_503", "score_404", "redirect", "oversized", "trailing_json", "null", "timeout"} {
		t.Run(fault, func(t *testing.T) {
			s, token := fixture(t)
			c, d := classifierFixture()
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if fault == "classify_401" {
					w.WriteHeader(401)
					return
				}
				if r.URL.Path == "/api/v1/classify" {
					writeJSON(w, 200, c)
					return
				}
				switch fault {
				case "score_503":
					w.WriteHeader(503)
				case "score_404":
					w.WriteHeader(404)
				case "redirect":
					http.Redirect(w, r, "http://untrusted.invalid", 302)
				case "oversized":
					w.Write([]byte(strings.Repeat(" ", 65537)))
				case "trailing_json":
					raw, _ := json.Marshal(d)
					w.Write(append(raw, []byte(` {"extra":true}`)...))
				case "null":
					w.Write([]byte("null"))
				case "timeout":
					time.Sleep(200 * time.Millisecond)
				}
			}))
			defer upstream.Close()
			s.classifier = upstream.URL
			s.client.Timeout = 100 * time.Millisecond
			s.store.Rules = Rules{Mode: "block", Threshold: 0.95, Blacklist: []string{"TEST"}}
			w := call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}})
			if w.Code != 200 {
				t.Fatal(w.Code, w.Body)
			}
			reopened, err := openStore(s.store.path)
			if err != nil {
				t.Fatal(err)
			}
			m := reopened.Messages[testMessage().ID]
			if m.Classified || m.Action != "allow" || m.Body != testMessage().Body {
				t.Fatal("fault lost or quarantined data", err, m)
			}
		})
	}
}

func TestScoreOutageRecoveryPreservesRestoreAndProvenance(t *testing.T) {
	s, token := fixture(t)
	c, d := classifierFixture()
	var available atomic.Bool
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/classify" {
			writeJSON(w, 200, c)
			return
		}
		if !available.Load() {
			w.WriteHeader(503)
			return
		}
		writeJSON(w, 200, d)
	}))
	defer upstream.Close()
	s.classifier = upstream.URL
	s.store.Rules = Rules{Mode: "block", Threshold: 0.99}
	call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{testMessage()}})
	call(t, s, "POST", "/api/v1/messages/"+testMessage().ID+"/restore", token, map[string]string{"operation_id": "restore-test-0001"})
	available.Store(true)
	s.refreshClassifications()
	m := s.store.Messages[testMessage().ID]
	if !m.Classified || !m.Restored || m.Action != "allow" || m.ClassifierAction != "block" || m.ClassifierReason != "risk_category:marketing" {
		t.Fatal(m)
	}
}

func TestConcurrentUploadsRetriesAndRestartConserveMessages(t *testing.T) {
	s, token := fixture(t)
	var wg sync.WaitGroup
	for i := 0; i < 30; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			m := testMessage()
			m.ID = fmt.Sprintf("concurrent-message-%03d", i)
			m.Received += int64(i)
			for retry := 0; retry < 3; retry++ {
				w := call(t, s, "POST", "/api/v1/messages/sync", token, map[string]any{"messages": []Message{m}})
				if w.Code != 200 {
					t.Error(w.Code)
				}
			}
		}(i)
	}
	wg.Wait()
	reopened, err := openStore(s.store.path)
	if err != nil || len(reopened.Messages) != 30 || reopened.Revision != 30 {
		t.Fatal("message conservation failed", err, len(reopened.Messages), reopened.Revision)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, ok := s.classifyContext(ctx, testMessage()); ok {
		t.Fatal("cancelled request classified")
	}
}

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"math"
	"net/http"
	"regexp"
	"strings"
)

var categories = map[string]bool{"personal": true, "otp": true, "service": true, "transaction": true, "marketing": true, "suspicious": true, "uncertain": true}

// Classification and ScoreDecision mirror the pinned upstream API contracts.
type ScoreDecision struct {
	Action    string  `json:"action"`
	Score     float64 `json:"score"`
	Reason    string  `json:"reason"`
	Model     string  `json:"modelVersion"`
	Threshold float64 `json:"thresholdUsed"`
	Category  string  `json:"category"`
	Review    bool    `json:"needsReview"`
}
type Classification struct {
	Primary    *Classification `json:"primary_classification,omitempty"`
	Source     string          `json:"-"`
	PendingLLM bool            `json:"-"`
	IsSpam     bool            `json:"is_spam"`
	Decision   *ScoreDecision  `json:"-"`
	Category   string          `json:"category"`
	Confidence float64         `json:"confidence"`
	Risk       float64         `json:"spam_score"`
	Review     bool            `json:"needs_review"`
	Calibrated bool            `json:"confidence_calibrated"`
	Model      string          `json:"model_version"`
}

func validClassification(c Classification) bool {
	return categories[c.Category] && strings.TrimSpace(c.Model) != "" && len(c.Model) <= 100 && !math.IsNaN(c.Confidence) && !math.IsInf(c.Confidence, 0) && c.Confidence >= 0 && c.Confidence <= 1 &&
		!math.IsNaN(c.Risk) && !math.IsInf(c.Risk, 0) && c.Risk >= 0 && c.Risk <= 1
}
func (s *Server) classify(m Message) (Classification, bool) {
	return s.classifyContext(context.Background(), m)
}
func (s *Server) classifyContext(ctx context.Context, m Message) (Classification, bool) {
	return s.classifyConfigured(ctx, m)
}
func (s *Server) classifyUpstream(ctx context.Context, m Message) (Classification, bool) {
	if s.classifier == "" {
		return Classification{}, false
	}
	var c Classification
	if !s.classifierRequest(ctx, "/api/v1/classify", map[string]string{"text": m.Body, "sender": m.Sender},
		[]string{"category", "confidence", "spam_score", "confidence_calibrated", "needs_review", "model_version", "is_spam"}, &c) || !validClassification(c) {
		return Classification{}, false
	}
	var decision ScoreDecision
	if !s.classifierRequest(ctx, "/sms/score", map[string]any{
		"address": m.Sender, "body": m.Body, "timestamp": m.Received, "localScore": 0,
		"threshold": s.store.Rules.Threshold, "profile": "conservative", "modelVersion": c.Model,
	}, []string{"action", "score", "reason", "modelVersion", "thresholdUsed", "category", "needsReview"}, &decision) {
		return Classification{}, false
	}
	// A hot model switch or incompatible response cannot authorize quarantine.
	if (decision.Action != "allow" && decision.Action != "block") || decision.Model != c.Model ||
		decision.Category != c.Category || decision.Review != c.Review || decision.Reason == "" ||
		len(decision.Reason) > 512 || !validProbability(decision.Score) || !validProbability(decision.Threshold) ||
		math.Abs(decision.Score-c.Risk) > 0.000001 {
		return Classification{}, false
	}
	// Validate upstream's documented contract; never invent a block from confidence.
	if decision.Action == "block" && (!c.IsSpam || !c.Calibrated || c.Review || (c.Category != "marketing" && c.Category != "suspicious")) {
		return Classification{}, false
	}
	c.Source = "privatesms"
	c.Decision = &decision
	return c, true
}

func validProbability(v float64) bool { return !math.IsNaN(v) && !math.IsInf(v, 0) && v >= 0 && v <= 1 }

func (s *Server) classifierRequest(ctx context.Context, path string, payload any, required []string, result any) bool {
	raw, err := json.Marshal(payload)
	if err != nil {
		return false
	}
	req, err := http.NewRequestWithContext(ctx, "POST", strings.TrimRight(s.classifier, "/")+path, bytes.NewReader(raw))
	if err != nil {
		return false
	}
	req.Header.Set("Content-Type", "application/json")
	if s.classifierKey != "" {
		req.Header.Set("X-API-Key", s.classifierKey)
	}
	response, err := s.client.Do(req)
	if err != nil {
		return false
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return false
	}
	raw, err = io.ReadAll(io.LimitReader(response.Body, 65537))
	if err != nil || len(raw) > 65536 {
		return false
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return false
	}
	for _, name := range required {
		value, exists := fields[name]
		if !exists || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return false
		}
	}
	return json.Unmarshal(raw, result) == nil
}

func applyPolicy(m Message, c Classification, ok bool, r Rules) Message {
	m.Action = "allow"
	m.Reason = "分类不可用，正常保留"
	m.Category = "uncertain"
	m.Review = true
	m.Classified = ok
	m.Source, m.LLMPending = c.Source, c.PendingLLM
	m.PrimaryClassification = c.Primary
	m.Confidence, m.Risk, m.Model = 0, 0, ""
	m.ClassifierAction, m.ClassifierReason, m.ClassifierThreshold = "", "", nil
	if !ok {
		return m
	}
	m.Category = c.Category
	m.Confidence = c.Confidence
	m.Risk = c.Risk
	m.Review = c.Review
	m.Model = c.Model
	if c.Decision != nil {
		m.ClassifierAction, m.ClassifierReason = c.Decision.Action, c.Decision.Reason
		m.ClassifierThreshold = &c.Decision.Threshold
	}
	m.Reason = "仅分类，正常保留"
	if m.Restored {
		m.Reason = "用户恢复"
		return m
	}
	if r.Mode == "classify" {
		return m
	}
	if c.Category == "otp" || c.Category == "transaction" || protectedContent.MatchString(m.Body) {
		m.Reason = "重要短信保护"
		return m
	}
	for _, sender := range r.Whitelist {
		if strings.TrimSpace(sender) == strings.TrimSpace(m.Sender) {
			m.Reason = "白名单保护"
			return m
		}
	}
	if c.Category == "uncertain" {
		m.Reason = "分类不确定，正常保留"
		return m
	}
	for _, sender := range r.Blacklist {
		if strings.TrimSpace(sender) == strings.TrimSpace(m.Sender) {
			m.Action = "quarantine"
			m.Reason = "用户黑名单规则"
			return m
		}
	}
	if c.Decision != nil {
		if c.Decision.Action == "block" {
			m.Action = "quarantine"
		}
		if c.Source == "llm" {
			m.Reason = "LLM: " + c.Decision.Reason
		} else {
			m.Reason = "PrivateSMS-Classifier: " + c.Decision.Reason
		}
	} else {
		m.Reason = "上游拦截决策不可用，正常保留"
	}
	return m
}

var protectedContent = regexp.MustCompile(`(?i)(验证码|校验码|动态码|验证代码|安全码|转账|扣款|交易提醒|账户安全|verification code|security code|one.time password|\botp\b|payment confirmation|transaction alert)`)

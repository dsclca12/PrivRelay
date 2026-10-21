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
var safety = regexp.MustCompile(`(?i)(验证码|校验码|动态码|交易|支付|扣款|余额|到账|verification|one.time|\botp\b|security code|[0-9]{4,8})`)

type Classification struct {
	Category   string  `json:"category"`
	Confidence float64 `json:"confidence"`
	Risk       float64 `json:"spam_score"`
	Review     bool    `json:"needs_review"`
	Calibrated bool    `json:"confidence_calibrated"`
	Model      string  `json:"model_version"`
}

func validClassification(c Classification) bool {
	return categories[c.Category] && c.Model != "" && !math.IsNaN(c.Confidence) && !math.IsInf(c.Confidence, 0) && c.Confidence >= 0 && c.Confidence <= 1 &&
		!math.IsNaN(c.Risk) && !math.IsInf(c.Risk, 0) && c.Risk >= 0 && c.Risk <= 1
}
func (s *Server) classify(m Message) (Classification, bool) {
	return s.classifyContext(context.Background(), m)
}
func (s *Server) classifyContext(ctx context.Context, m Message) (Classification, bool) {
	if s.classifier == "" {
		return Classification{}, false
	}
	raw, _ := json.Marshal(map[string]string{"text": m.Body, "sender": m.Sender})
	req, err := http.NewRequestWithContext(ctx, "POST", strings.TrimRight(s.classifier, "/")+"/api/v1/classify", bytes.NewReader(raw))
	if err != nil {
		return Classification{}, false
	}
	req.Header.Set("Content-Type", "application/json")
	if s.classifierKey != "" {
		req.Header.Set("X-API-Key", s.classifierKey)
	}
	response, err := s.client.Do(req)
	if err != nil {
		return Classification{}, false
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return Classification{}, false
	}
	var fields map[string]json.RawMessage
	if json.NewDecoder(io.LimitReader(response.Body, 65536)).Decode(&fields) != nil {
		return Classification{}, false
	}
	for _, name := range []string{"category", "confidence", "spam_score", "confidence_calibrated", "needs_review", "model_version"} {
		if value, ok := fields[name]; !ok || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return Classification{}, false
		}
	}
	rawResult, _ := json.Marshal(fields)
	var c Classification
	if json.Unmarshal(rawResult, &c) != nil || !validClassification(c) {
		return Classification{}, false
	}
	return c, true
}
func applyPolicy(m Message, c Classification, ok bool, r Rules) Message {
	m.Action = "allow"
	m.Reason = "分类不可用，正常保留"
	m.Category = "uncertain"
	m.Review = true
	m.Classified = ok
	if !ok {
		return m
	}
	m.Category = c.Category
	m.Confidence = c.Confidence
	m.Risk = c.Risk
	m.Review = c.Review
	m.Model = c.Model
	m.Reason = "仅分类，正常保留"
	if m.Restored {
		m.Reason = "用户恢复"
		return m
	}
	if r.Mode == "classify" {
		return m
	}
	if c.Category == "otp" || c.Category == "transaction" || safety.MatchString(m.Body) {
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
	if (c.Category == "marketing" || c.Category == "suspicious") && c.Calibrated && !c.Review && c.Confidence >= r.Threshold {
		m.Action = "quarantine"
		m.Reason = "已校准模型达到用户阈值"
	} else {
		m.Reason = "未达到可靠隔离条件，正常保留"
	}
	return m
}

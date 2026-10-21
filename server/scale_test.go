package main

import (
	"encoding/json"
	"fmt"
	"testing"
)

func TestSearchAndAggregatesAcrossTenThousandMessages(t *testing.T) {
	s, token := fixture(t)
	for i := 0; i < 10000; i++ {
		m := testMessage()
		m.ID = fmt.Sprintf("synthetic-message-%05d", i)
		m.Received, m.Revision = int64(1000+i), int64(i+1)
		m.Category, m.Action = "marketing", "allow"
		m.Classified = true
		if i%2 == 0 {
			m.Action, m.Reason = "quarantine", "synthetic blacklist"
		}
		if i%5 == 0 {
			m.Restored, m.Action = true, "allow"
		}
		s.store.Messages[m.ID] = m
	}
	var page struct {
		Messages []Message `json:"messages"`
		Total    int       `json:"total"`
		More     bool      `json:"has_more"`
	}
	w := call(t, s, "GET", "/api/v1/messages/search?offset=9950&limit=50", token, nil)
	json.Unmarshal(w.Body.Bytes(), &page)
	if w.Code != 200 || page.Total != 10000 || len(page.Messages) != 50 || page.More || page.Messages[49].ID != "synthetic-message-00000" {
		t.Fatal("last historical page", w.Body)
	}
	w = call(t, s, "GET", "/api/v1/filter/quarantine?offset=3950&limit=50", token, nil)
	json.Unmarshal(w.Body.Bytes(), &page)
	if page.Total != 4000 || len(page.Messages) != 50 || page.More {
		t.Fatal("quarantine pagination", w.Body)
	}
	var status struct {
		Messages, Quarantined, Restored int
		Reasons                         map[string]int `json:"quarantine_reasons"`
	}
	w = call(t, s, "GET", "/api/v1/status", token, nil)
	json.Unmarshal(w.Body.Bytes(), &status)
	if status.Messages != 10000 || status.Quarantined != 4000 || status.Restored != 2000 || status.Reasons["synthetic blacklist"] != 4000 {
		t.Fatal("global aggregates", w.Body)
	}
}

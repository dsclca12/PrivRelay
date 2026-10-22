package main

import (
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func TestHTTPSProxyCookieWebsocketAndCSRF(t *testing.T) {
	s, token := fixture(t)
	upstream := httptest.NewServer(s.handler())
	defer upstream.Close()
	target, _ := url.Parse(upstream.URL)
	proxy := httputil.NewSingleHostReverseProxy(target)
	original := proxy.Director
	proxy.Director = func(r *http.Request) { original(r); r.Header.Set("X-Forwarded-Proto", "https") }
	front := httptest.NewTLSServer(proxy)
	defer front.Close()
	client := front.Client()
	client.Jar, _ = cookiejar.New(nil)
	req, _ := http.NewRequest("POST", front.URL+"/api/v1/session", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Origin", front.URL)
	response, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 200 {
		t.Fatal("proxy session failed", response.StatusCode)
	}
	cookies := response.Cookies()
	if len(cookies) != 1 || !cookies[0].Secure || !cookies[0].HttpOnly || cookies[0].SameSite != http.SameSiteStrictMode {
		t.Fatal("insecure proxy cookie", cookies)
	}
	response, err = client.Get(front.URL + "/api/v1/messages")
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 200 {
		t.Fatal("HTTPS cookie rejected", response.StatusCode)
	}
	req, _ = http.NewRequest("PUT", front.URL+"/api/v1/filter/rules", strings.NewReader(`{"mode":"classify","threshold":0.95}`))
	req.Header.Set("Origin", "https://untrusted.example")
	response, err = client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 401 {
		t.Fatal("cross-origin mutation accepted", response.StatusCode)
	}
	dialer := websocket.Dialer{TLSClientConfig: client.Transport.(*http.Transport).TLSClientConfig, HandshakeTimeout: time.Second}
	url, _ := url.Parse(front.URL + "/api/v1/ws")
	header := http.Header{"Origin": []string{front.URL}}
	for _, cookie := range client.Jar.Cookies(url) {
		header.Add("Cookie", cookie.String())
	}
	socket, _, err := dialer.Dial("wss"+strings.TrimPrefix(front.URL, "https")+"/api/v1/ws", header)
	if err != nil {
		t.Fatal("proxy websocket failed", err)
	}
	defer socket.Close()
	call(t, s, "PUT", "/api/v1/filter/rules", token, Rules{Mode: "classify", Threshold: .95})
	socket.SetReadDeadline(time.Now().Add(time.Second))
	var event map[string]string
	if err = socket.ReadJSON(&event); err != nil || event["event"] != "changed" {
		t.Fatal("proxy push failed", event, err)
	}
}

// Copy to config.js and adjust. config.js is gitignored (it may hold broker creds).
// URL query params override any of these, e.g. ?gw=dkm440-gw1-test&wss=ws://localhost:9001
window.OSOS_CONFIG = {
  wssUrl: "wss://broker.emqx.io:8084/mqtt", // browser connection to the broker
  username: "",                             // empty = anonymous (playground only)
  password: "",
  gwId: "dkm440-gw1",
  confMin: 0.90,                            // below this the drawing is rejected
};

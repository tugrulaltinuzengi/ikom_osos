#pragma once
// Parse and execute one command JSON ({"id","action","args"}) received on
// osos/{gw}/cmd; always answers with an ack on osos/{gw}/ack.
void cmd_handle(const char *json, int len);

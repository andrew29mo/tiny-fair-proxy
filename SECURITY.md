# Security scope

Experimental local TCP forwarding for trusted operators and configuration. Use
loopback listeners by default. The tenant listener is a classification, not an
identity check; source IP is not authentication. This is not a sandbox, VPN,
firewall, DDoS mitigation product or hardened public gateway. TLS is opaque and
end-to-end; no payload logging or TLS termination is performed.

Only configured numeric backend addresses can be reached through a listener.
Apply OS/network access control before exposing listeners. Application payload
buffers and admitted connections are bounded, but kernel buffers, accept backlog,
CPU under connection floods and entire-process memory are not hard-capped.

Reports use synthetic payloads and whitelisted runtime provenance. Do not commit
state directories, toolchains, credentials, personal settings or private traffic.
Actions use read-only tokens and pinned actions; third-party dependency updates
require review. No crash-recovery or delivery guarantee exists for live sockets.

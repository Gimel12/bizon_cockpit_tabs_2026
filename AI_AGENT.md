# BIZON AI workstation assistant

BIZON AI combines chat with optional computer control in the existing Cockpit tab. It supports a local Ollama model, a local OpenAI-compatible model server, or Anthropic Claude. The selected model can request shell commands, read text files, and write text files when **Computer control** is enabled. The interface shows each requested action and its result.

The new assistant uses Cockpit's authenticated process channels. It does not open another network port and does not replace the existing BIZON API or its restricted diagnostic service.

## Using the chat interface

**Hide chats / Show chats** expands the conversation area and remembers the desktop sidebar preference in the browser. On narrow screens, recent chats open as a drawer; its close button, the background, or Escape dismisses it. No messages or credentials are stored in browser storage.

Search recent chats by title. The **…** button beside a chat opens Rename and Delete actions; deletion requires a second confirmation. Chats are grouped by date. Use **New chat** for a fresh conversation, or click the model below the BIZON AI title to open provider settings.

Each message has a Copy button. **Use as draft** copies an earlier user message into the composer for editing without changing history or sending it. It also turns computer control off. Responses include separate Copy code buttons. While an answer is arriving, scrolling upward keeps your reading position; **Latest message** returns to the bottom. The composer grows with its text and supports Enter to send and Shift+Enter for a new line.

When focus is inside the AI tab, Ctrl/Cmd+K opens chat search, and Ctrl/Cmd+Shift+O starts a new chat when no request is running. Neither shortcut executes a computer action.

## Choose a provider

Open **Bizon AI → AI settings**.

### Local Ollama

1. Select **Local · Ollama**.
2. Use the workstation's loopback address, normally `http://127.0.0.1:11434`.
3. Choose **Test connection & list models**, select an installed model, and save.

The assistant selects the first discovered local model when no model has been saved. Computer control requires a model that supports native tool calling. The workstation used for initial validation has `qwen3.8:27b`, a quantized 27.3B model, served by Ollama. Its actual memory use depends on context and other GPU workloads; availability is checked at runtime.

The Ollama adapter uses its native `/api/chat` protocol, a 32,768-token context setting, and up to 4,096 generated tokens per model call. It requests thinking output to be disabled; private thinking fields from providers are never displayed.

### Local OpenAI-compatible server

Select **Local · OpenAI-compatible server**, enter its loopback URL and port, then discover or enter a model. For example, a separately configured vLLM server may use `http://127.0.0.1:8000/v1`.

The server must implement `/v1/models` and streaming `/v1/chat/completions`, including native tool calls for computer control. The assistant does not install or start model servers. Separately authenticated local endpoints are not currently configurable in this interface.

Only explicit loopback addresses or `localhost` are accepted for local servers. Remote hosts, credentials in URLs, arbitrary URL paths, redirects, and environment-configured HTTP proxies are rejected or disabled.

### Anthropic Claude

1. Select **Cloud · Anthropic Claude**.
2. Enter an Anthropic API key and save it.
3. Choose **Test connection & list models**, select or enter an available model, and save.

The key is sent to the host through Cockpit's authenticated channel and stored in the signed-in user's private configuration. It is not returned by status/model-list responses, saved in browser storage, or included in model conversation payloads. It is used only in the authentication header to the fixed Anthropic API endpoint. Leaving the key field blank preserves the saved key; **Remove saved key** deletes it.

Choosing Claude sends the conversation context, selected attachment contents/images, and requested tool results to Anthropic. Local inference does not automatically fall back to Claude. Review attachments and the tasks you authorize before selecting a cloud provider. Local inference keeps the model conversation on the workstation; commands you authorize can still make network connections or use external services.

## Computer control and permissions

New chats and reopened conversations start with **Computer control** off. In this mode the assistant can answer questions and analyze attachments, but the planner does not dispatch tools.

With **Computer control** enabled, tools run as the signed-in account. **User mode is not a sandbox.** It has that account's existing permissions, including any access granted by Docker, LXD, sudo configuration, mounted shares, or other local services. On images where `bizon` belongs to Docker or LXD groups, those memberships can provide routes to administrative authority.

**Administrator for this request** explicitly authorizes a root executor through Cockpit's existing authentication/elevation mechanism. The assistant does not request, store, or forward a sudo password. The grant is scoped to the current request; finishing, stopping, opening another chat, or losing Cockpit administrative permission closes the executor. A later request requires enabling the administrator choice again. Cockpit may reuse administrative authentication according to its own session policy.

An administrator executor has broad root authority. It can change or delete system files, install software, access credentials, or launch services. Neither a model prompt nor secret redaction is a security boundary against a deliberately authorized root command. User-mode commands can also access the signed-in user's credentials. The tool channel validates protocol fields and run identifiers; this protects request routing, not the safety of arbitrary shell text chosen by a model.

Use precise task requests, inspect the action cards, and keep an independent backup before authorizing changes to valuable data. Stopping a request does not undo completed commands, file writes, package changes, or services/containers that an authorized command started separately.

## Stop, timeouts, and limits

**Stop** closes both planner and executor channels and revokes the current run. The planner also exits on input EOF or termination. Active commands are stopped through their systemd control group where available, with process-group termination as a fallback. Loss of administrative permission stops an active administrator run.

Limits are enforced outside the model prompt:

| Item | Limit |
| --- | --- |
| Concurrent planner requests | One per signed-in user, enforced with a host file lock |
| Tool calls per chat request | 16 |
| Overall request and UI grant | 30 minutes |
| Requested command timeout | Planner accepts 1–300 seconds; executor defaults to 120 seconds and independently caps requests at 600 seconds |
| Model discovery | Five-second deadline |
| Streamed command output | 128 KiB in the executor; smaller bounded excerpts go into model context and saved history |
| File reads | Up to 256 KiB; regular files only |
| File writes | Planner accepts up to 65,536 characters; executor independently caps encoded content at 256 KiB |
| Attachments | Up to four; bounded text and images; images at most 2 MiB each |
| Saved conversation | At most 160 messages, with older message pairs removed when the bounded storage size is exceeded |

On the supported Linux/systemd path, command units have process and memory limits: 128 tasks, no swap, and memory capped at one quarter of physical RAM within a 512 MiB–8 GiB range. These are command-execution limits, not limits on the separately running Ollama/vLLM service or services an administrator deliberately starts outside the unit.

A blocked filesystem or kernel operation may not respond immediately to termination. File operations can wait on failing drives or unavailable network filesystems; Stop is not a guarantee that such an operation instantly disappears. The interface should not be treated as a recovery tool for a machine whose kernel or storage is already unresponsive.

## Private settings and history

Each signed-in account uses:

```text
~/.local/share/bizon-ai-agent/
    config.json
    active.lock
    history/<conversation-uuid>.json
```

The profile and history directories use mode `0700`. Configuration, lock, and history files use mode `0600` and are owned by the account. Profile validation rejects unsafe ownership, writable shared paths, and symlinked profile components. Existing private data files are tightened to `0600` when opened.

History contains user/assistant text and bounded action summaries/results. Images are not retained in history. Native provider tool messages are transient; opening a conversation with a different provider cannot replay orphaned tool-call messages. Removing a conversation deletes its local history file.

The backend masks configured keys and recognizable credentials before sending tool results into model context, emitting answers, or saving history. Streaming redaction handles split keys and private-key blocks. This reduces accidental disclosure but cannot identify every possible secret embedded in arbitrary files, command output, or images. Sensitive documents should not be attached merely because redaction exists.

The planner is `cockpit_bizon_ai/agent/backend.py`; provider adapters are in `provider.py`. It never executes model-requested commands itself. `executor.py` runs separately under the authority of its Cockpit channel, validates every request, and accepts only requests for its live run identifier and nonce. The nonce is held in browser memory for that request and is not saved in history or browser storage.

## Before cloning the OS

Stop all AI requests and close customer/test sessions before image sealing. Remove **the entire `~/.local/share/bizon-ai-agent/` profile for every account included in the image**, including `bizon` and any administrator account used for testing. This removes saved provider keys, conversations, action output, and stale lock files. Do not copy a maintainer's profile into `/etc/skel` or another account template.

Keep the root-owned application code and intended local model files. Profile directories are created privately on first use. This cleanup is part of image sealing; it does not occur automatically when updating the tab or deleting one conversation. Verify that no provider key or test history remains in the final Rescuezilla source image.

The factory workstation's `/usr/local/sbin/bizon-seal-image` was updated to remove both the `bizon` and root AI profiles. The sealing command was not run as part of this update. Other provisioning systems must add equivalent cleanup for every account included in their image.

## Validation and known boundaries

Run the focused suites from the repository root:

```sh
python3 -m unittest test_agent_backend test_ai_executor
NODE_PATH=/path/to/node_modules node test_ai_ui.cjs
```

The UI suite requires the project's test dependency `jsdom`. Backend tests cover multi-step native tool loops, errors, tool limits, provider changes, private storage, secret redaction, malformed responses, split SSE events, and actual subprocess EOF/SIGTERM cleanup. Executor and UI tests cover their separate authority and lifecycle boundaries.

A live Claude test requires a configured key. No Anthropic key was available during initial validation, so Claude protocol handling was exercised with fixtures rather than a paid live API request. Test model discovery, a normal answer, a harmless read-only tool request, and Stop after configuring a real key. The same end-to-end checks are required for each different OpenAI-compatible local server/model; a compatible protocol alone does not establish reliable model behavior.

Automated tests and successful local probes do not guarantee every model, command, kernel state, or hardware combination. Keep provider/service availability and the distinction between completed actions and model suggestions visible when reviewing results.

### Release validation, 2026-11-04

For v6.1.12, 41 backend/executor tests, 28 AI UI checks, 11 workspace checks, 35 shared-theme checks, and 20 updater/navigation tests passed. The installed signed release passed all 49 workstation acceptance checks, including API authorization rejection and three VNC authentication/framebuffer/cleanup cycles.

`validate_ai_agent.py` tested the installed helpers against the live local model: chat with no tool execution, writing and reading a disposable file, and an explicitly constrained administrator `id -u` command. All three passed. The harness limits accepted model actions to those exact test operations; it does not grant arbitrary model commands during validation.

Live browser checks covered local model discovery, the Claude configuration fields, formatted table output, reopening saved history, and stopping generation. Administrator execution was verified through the helper integration and mocked Cockpit UI lifecycle tests; the browser's administrator checkbox was not exercised against a live task. Claude and separate OpenAI-compatible servers remain unverified with live provider credentials/services.

For the v6.1.13 chat-interface refinement, 47 backend/executor tests, 28 AI UI checks, 25 chat-interaction checks, 11 workspace checks, 35 theme checks, and 20 updater/navigation tests passed. The new checks cover collapse persistence, search, rename, copy, draft reuse, scroll position, mobile dismissal, and delayed deletion/attachment races. Live browser checks verified local chat, remembered sidebar state, rename/search, copy feedback, draft reuse, both themes, and the 390-pixel mobile drawer. Renaming preserves message/action data and uses the existing private profile lock.

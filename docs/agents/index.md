# AI Agents — Design Docs

Architecture decisions and reference material for the AI agent feature set.

## Setup

- [AI Agents — Setup](ai-agent-setup.md) — install, configure agents/tools,
  endpoints, and the native SSE streaming protocol.

## Design

- The wire protocol is native SSE (no AG-UI / Vercel AI Data Stream); the
  per-agent `backend` selection model is
  `"pydantic_ai" | "langchain" | "auto"` (see the Design notes section of the
  setup guide).

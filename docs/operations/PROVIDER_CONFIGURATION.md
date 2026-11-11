# Hire-Steward — AI Provider Configuration & Credential Management

**Product:** Hire-Steward / JobPilot  
**Security Standard:** Strict Secret Encapsulation, Disabled-by-Default Inference, Pre-Socket Budget Fencing  

---

## 1. Overview

Hire-Steward features a provider-neutral AI architecture supporting five primary inference and evaluation providers:
1. **Groq LPU:** Ultra-fast open-weights inference (Llama 3.3, Mixtral).
2. **Google Gemini:** Multimodal and reasoning models (Gemini 2.0 Flash, Gemini 1.5 Pro).
3. **Anthropic Claude:** High-precision evaluation (Claude Sonnet 3.5).
4. **OpenAI GPT:** Structured schema generation (GPT-4o, reasoning models).
5. **Local Ollama:** Self-hosted, private offline inference on `http://127.0.0.1:11434`.

By default, the application operates in **OFFLINE_MOCK** mode (`IMPLEMENTED_AND_VERIFIED`) with **zero paid external API calls**, zero network egress, and zero credential assumptions.

External cloud AI providers (Groq, Gemini, Anthropic, OpenAI) are classified as `IMPLEMENTED_NOT_FULLY_VERIFIED`: the adapters, payload builders, response parsers, SecretStr protections, and pre-socket budget reservations are implemented and verified via deterministic mock contracts; live production inference will be enabled only when the user sets the appropriate API keys below.

---

## 2. Setting Up API Keys

When you are ready to enable frontier or cloud AI providers, set the appropriate environment variables in your system or in your local `.env` file.

### Supported Environment Variables:

```env
# Groq Cloud API Key
HIRE_STEWARD_GROQ_API_KEY=gsk_your_groq_api_key_here

# Google Gemini API Key
HIRE_STEWARD_GEMINI_API_KEY=AIzaSy_your_gemini_api_key_here

# Anthropic Claude API Key
HIRE_STEWARD_ANTHROPIC_API_KEY=sk-ant-your_anthropic_api_key_here

# OpenAI API Key
HIRE_STEWARD_OPENAI_API_KEY=sk-proj-your_openai_api_key_here

# Local Ollama Base URL (Optional - defaults to http://127.0.0.1:11434)
HIRE_STEWARD_OLLAMA_BASE_URL=http://127.0.0.1:11434
```

> [!IMPORTANT]
> Never commit `.env` or files containing plaintext API keys to Git. The `.gitignore` is pre-configured to exclude all `.env*` files and local credential caches.

---

## 3. How Credentials Are Protected

Hire-Steward enforces four cryptographic and software security invariants:
1. **Pydantic SecretStr Wrapping:** All API keys are loaded into Pydantic models using `SecretStr` with `repr=False`. Even if an unhandled exception or debug dump occurs, keys are masked as `**********` and will never appear in server logs, HTTP responses, or stack traces.
2. **Pre-Flight Missing Key Classification:** If an API key is missing or empty, the adapter immediately halts and returns `HTTP_401_AUTH_REVOKED` without opening a network socket.
3. **Hard Budget Reservation Gate:** Before any API call is dispatched, the budget tracker calculates worst-case token liability and reserves funds against the hard budget cap ($5.00 default). If remaining funds are insufficient, the request is rejected pre-socket.
4. **Disabled-by-Default:** Paid AI features remain disabled until explicitly authorized by the user in Settings (`ai_provider_mode`).

---

## 4. Verifying Provider Readiness

To inspect the status of your configured providers without making paid inference calls:

### Via Web Workbench:
Navigate to the **AI Usage & Budget** view (`Screen 10`) at:
```
http://127.0.0.1:8000/#ai-usage
```
The provider readiness cards will show:
- `ACTIVE_DEFAULT`: Offline mock evaluator (always ready, $0.00 cost).
- `READY`: Key detected and ready for authorized inference.
- `NEEDS_KEY`: Provider not yet configured (safe fallback active).

### Via API Endpoint:
```bash
curl http://127.0.0.1:8000/api/v1/ai/status
```
Response:
```json
{
  "active_mode": "OFFLINE_MOCK",
  "paid_ai_enabled": false,
  "has_groq_key": true,
  "has_gemini_key": true,
  "has_anthropic_key": false,
  "has_openai_key": false,
  "has_ollama": true,
  "budget_cap_usd": 5.0,
  "remaining_budget_usd": 5.0,
  "supported_providers": ["offline_mock", "groq", "gemini", "anthropic", "openai", "ollama"]
}
```
No secret keys are ever returned in API responses.

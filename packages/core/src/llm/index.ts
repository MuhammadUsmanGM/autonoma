export { BaseLLMProvider } from "./base.js";
export {
  OpenAICompatibleProvider,
  OpenAIProvider,
  AnthropicProvider,
} from "./openai-compatible.js";

import type { LLMProvider } from "../types.js";
import { OpenAIProvider, AnthropicProvider, OpenAICompatibleProvider } from "./openai-compatible.js";

export function createLLMProvider(config: {
  provider: string;
  apiKey: string;
  model?: string;
  baseUrl?: string;
}): LLMProvider {
  switch (config.provider) {
    case "openai":
      return new OpenAIProvider(config.apiKey, config.model);
    case "anthropic":
    case "claude":
      return new AnthropicProvider(config.apiKey, config.model);
    default:
      if (config.baseUrl) {
        return new OpenAICompatibleProvider({
          name: config.provider,
          apiKey: config.apiKey,
          baseUrl: config.baseUrl,
          defaultModel: config.model ?? "default",
        });
      }
      throw new Error(`Unknown LLM provider: ${config.provider}`);
  }
}

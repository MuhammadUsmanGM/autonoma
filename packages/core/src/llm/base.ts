import type { LLMProvider, LLMMessage, LLMOptions } from "../types.js";

export abstract class BaseLLMProvider implements LLMProvider {
  abstract name: string;
  abstract chat(messages: LLMMessage[], options?: LLMOptions): Promise<string>;

  protected buildMessages(
    messages: LLMMessage[],
    systemPrompt?: string
  ): LLMMessage[] {
    if (systemPrompt) {
      return [{ role: "system", content: systemPrompt }, ...messages];
    }
    return messages;
  }
}

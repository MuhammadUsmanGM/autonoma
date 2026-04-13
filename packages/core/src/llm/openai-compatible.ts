import { BaseLLMProvider } from "./base.js";
import type { LLMMessage, LLMOptions } from "../types.js";

export class OpenAICompatibleProvider extends BaseLLMProvider {
  name: string;
  private apiKey: string;
  private baseUrl: string;
  private defaultModel: string;

  constructor(config: {
    name: string;
    apiKey: string;
    baseUrl: string;
    defaultModel: string;
  }) {
    super();
    this.name = config.name;
    this.apiKey = config.apiKey;
    this.baseUrl = config.baseUrl;
    this.defaultModel = config.defaultModel;
  }

  async chat(messages: LLMMessage[], options?: LLMOptions): Promise<string> {
    const allMessages = this.buildMessages(messages, options?.systemPrompt);
    const model = options?.model ?? this.defaultModel;

    const response = await fetch(`${this.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages: allMessages,
        temperature: options?.temperature ?? 0.7,
        max_tokens: options?.maxTokens ?? 4096,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`LLM API error (${response.status}): ${error}`);
    }

    const data = (await response.json()) as {
      choices: Array<{ message: { content: string } }>;
    };
    return data.choices[0].message.content;
  }
}

export class OpenAIProvider extends OpenAICompatibleProvider {
  constructor(apiKey: string, model = "gpt-4o") {
    super({
      name: "openai",
      apiKey,
      baseUrl: "https://api.openai.com/v1",
      defaultModel: model,
    });
  }
}

export class AnthropicProvider extends BaseLLMProvider {
  name = "anthropic";
  private apiKey: string;
  private defaultModel: string;

  constructor(apiKey: string, model = "claude-sonnet-4-6") {
    super();
    this.apiKey = apiKey;
    this.defaultModel = model;
  }

  async chat(messages: LLMMessage[], options?: LLMOptions): Promise<string> {
    const model = options?.model ?? this.defaultModel;
    const systemPrompt = options?.systemPrompt ?? messages.find(m => m.role === "system")?.content;
    const chatMessages = messages.filter(m => m.role !== "system");

    const response = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": this.apiKey,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model,
        max_tokens: options?.maxTokens ?? 4096,
        system: systemPrompt,
        messages: chatMessages.map(m => ({
          role: m.role,
          content: m.content,
        })),
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Anthropic API error (${response.status}): ${error}`);
    }

    const data = (await response.json()) as {
      content: Array<{ text: string }>;
    };
    return data.content[0].text;
  }
}

import type { Skill } from "../types.js";

export class SkillRegistry {
  private skills = new Map<string, Skill>();

  register(skill: Skill): void {
    if (this.skills.has(skill.name)) {
      throw new Error(`Skill "${skill.name}" is already registered`);
    }
    this.skills.set(skill.name, skill);
  }

  unregister(name: string): void {
    this.skills.delete(name);
  }

  get(name: string): Skill | undefined {
    return this.skills.get(name);
  }

  list(): Skill[] {
    return [...this.skills.values()];
  }

  getToolDescriptions(): string {
    return this.list()
      .map((s) => {
        const params = s.parameters
          ?.map((p) => `  - ${p.name} (${p.type}${p.required ? ", required" : ""}): ${p.description}`)
          .join("\n");
        return `- **${s.name}**: ${s.description}${params ? `\n${params}` : ""}`;
      })
      .join("\n");
  }
}

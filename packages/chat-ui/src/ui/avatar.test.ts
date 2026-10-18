import { describe, expect, it } from "vitest";
import { avatarUrl, initialsOf } from "./avatar";

describe("avatar (docs/design/avatars.md)", () => {
  it("takes up to two initials, from the first and last word, upper case", () => {
    expect(initialsOf("Jan Peeters")).toBe("JP");
    expect(initialsOf("Marie-Claire De Smet")).toBe("MS");
    expect(initialsOf("émile")).toBe("É");
    expect(initialsOf("  Development (sign-in off) ")).toBe("DO");
    expect(initialsOf("")).toBe("?");
    expect(initialsOf("123")).toBe("?");
  });

  it("keys the picture's URL by its ETag, and has none without one", () => {
    expect(avatarUrl("user-1", "abc123")).toBe("/v1/users/user-1/avatar?v=abc123");
    expect(avatarUrl("user-1", null)).toBeNull();
    expect(avatarUrl("user-1", undefined)).toBeNull();
  });
});

"use server";

import { signIn, signOut } from "@/auth";

export async function signInWithGoogle(formData: FormData) {
  const next = String(formData.get("next") || "/home");
  // only paths on this site: "//evil.com" and "/\\evil.com" are other sites to a browser
  const safe = /^\/(?![\/\\])/.test(next) ? next : "/home";
  await signIn("google", { redirectTo: safe });
}

export async function signOutAction() {
  await signOut({ redirectTo: "/" });
}

"use server";

import { signIn, signOut } from "@/auth";

export async function signInWithGoogle(formData: FormData) {
  const next = String(formData.get("next") || "/home");
  await signIn("google", { redirectTo: next.startsWith("/") ? next : "/home" });
}

export async function signOutAction() {
  await signOut({ redirectTo: "/" });
}

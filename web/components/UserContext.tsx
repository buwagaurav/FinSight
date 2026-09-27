"use client";

import { createContext, ReactNode, useContext } from "react";
import type { SessionUser } from "@/auth";

type Ctx = { user: SessionUser | null; authEnabled: boolean };
const UserCtx = createContext<Ctx>({ user: null, authEnabled: false });

export function UserProvider({ user, authEnabled, children }: Ctx & { children: ReactNode }) {
  return <UserCtx.Provider value={{ user, authEnabled }}>{children}</UserCtx.Provider>;
}

export const useUser = () => useContext(UserCtx);

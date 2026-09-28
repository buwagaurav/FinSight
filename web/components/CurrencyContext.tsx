"use client";

import { createContext, useContext } from "react";
import type { Currency } from "@/lib/format";

// The currency of the company being viewed, so every figure on its page is formatted the same way
const CurrencyCtx = createContext<Currency>("INR");

export const CurrencyProvider = CurrencyCtx.Provider;
export const useCurrency = () => useContext(CurrencyCtx);

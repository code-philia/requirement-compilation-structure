import type { ComponentProps, PropsWithChildren } from "react";
import { ConfigProvider } from "@arco-design/web-react";
import zhCN from "@arco-design/web-react/es/locale/zh-CN";
import "@arco-design/web-react/dist/css/arco.css";

type Locale = ComponentProps<typeof ConfigProvider>["locale"];

// Application copy remains requirement-owned. Override locale for other languages.
export function DesignSystemProvider({ children, locale = zhCN }: PropsWithChildren<{ locale?: Locale }>) {
  return <ConfigProvider locale={locale}>{children}</ConfigProvider>;
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageSquare, ChevronsLeft } from "lucide-react";
import {
  SidebarProvider,
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarInset,
  useSidebar,
} from "@/components/ui/sidebar";
import { Logo } from "@/components/ui/logo";
import { TracesProvider } from "@/context/traces-context";
import "./globals.css";
import "./traces.css";

const NAV_ITEMS = [
  { href: "/sessions", label: "Sessions", icon: MessageSquare },
];

function TracesSidebar() {
  const pathname = usePathname();
  const { toggleSidebar } = useSidebar();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2 px-2 py-1 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:justify-center">
          <Link href="/sessions" className="group-data-[collapsible=icon]:hidden">
            <Logo size="sm" />
          </Link>
          <Link href="/sessions" className="hidden group-data-[collapsible=icon]:inline-flex">
            <Logo size="sm" collapsed />
          </Link>
          <button
            onClick={toggleSidebar}
            className="ml-auto h-7 w-7 shrink-0 inline-flex items-center justify-center rounded-md hover:bg-muted transition-colors group-data-[collapsible=icon]:hidden"
          >
            <ChevronsLeft className="size-4" />
          </button>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_ITEMS.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    asChild
                    isActive={pathname.startsWith(item.href)}
                    tooltip={item.label}
                  >
                    <Link href={item.href}>
                      <item.icon className="size-4" />
                      <span>{item.label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        <TracesProvider>
          <SidebarProvider defaultOpen={false} className="!min-h-0 h-svh overflow-hidden">
            <TracesSidebar />
            <SidebarInset className="overflow-hidden">
              <div className="flex-1 flex flex-col overflow-y-auto">{children}</div>
            </SidebarInset>
          </SidebarProvider>
        </TracesProvider>
      </body>
    </html>
  );
}

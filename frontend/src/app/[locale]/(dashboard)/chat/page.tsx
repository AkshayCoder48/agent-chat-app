"use client";

import { useState } from "react";
import { ChatContainer, ConversationSidebar } from "@/components/chat";
import { FileSidebar } from "@/components/chat/file-sidebar";
import { Button } from "@/components/ui/button";
import { FolderOpen, X } from "lucide-react";

export default function ChatPage() {
  const [filePanelOpen, setFilePanelOpen] = useState(false);
  return (
    <div className="-mx-3 -mt-4 -mb-8 flex min-h-0 flex-1 sm:-mx-6 sm:-mt-8 lg:-mb-8">
      <ConversationSidebar />
      <div className="relative min-w-0 flex-1">
        <ChatContainer />
        {/* Toggle button for the file sidebar (right side) */}
        <Button
          variant="outline"
          size="sm"
          onClick={() => setFilePanelOpen((v) => !v)}
          className="absolute right-3 top-3 z-20 h-8 gap-1.5 text-xs shadow-sm bg-card/95 backdrop-blur"
          title={filePanelOpen ? "Hide files" : "Show files"}
        >
          {filePanelOpen ? (
            <>
              <X className="h-3.5 w-3.5" /> Hide
            </>
          ) : (
            <>
              <FolderOpen className="h-3.5 w-3.5" /> Files
            </>
          )}
        </Button>
      </div>
      {filePanelOpen && (
        <aside className="hidden md:block w-72 lg:w-80 shrink-0 slide-in-right">
          <FileSidebar />
        </aside>
      )}
    </div>
  );
}

"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";

interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
}

interface Chat {
  id: number;
  title: string | null;
  createdAt: string;
}

export default function ChatPage() {
  const router = useRouter();
  const [chats, setChats] = useState<Chat[]>([]);
  const [selectedChatId, setSelectedChatId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchChats();
  }, []);

  useEffect(() => {
    if (selectedChatId) {
      fetchMessages(selectedChatId);
    } else {
      setMessages([]);
    }
  }, [selectedChatId]);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const fetchChats = async () => {
    try {
      const response = await fetch("/api/llm/chats");
      if (response.ok) {
        const data = await response.json();
        setChats(data.chats);
      }
    } catch (error) {
      console.error("Failed to fetch chats:", error);
    }
  };

  const fetchMessages = async (chatId: number) => {
    try {
      const response = await fetch(`/api/llm/chats/${chatId}`);
      if (response.ok) {
        const data = await response.json();
        setMessages(data.messages);
      }
    } catch (error) {
      console.error("Failed to fetch messages:", error);
    }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput("");
    setIsLoading(true);

    // Add user message to UI immediately
    const tempUserMessage: Message = {
      id: Date.now(),
      role: "user",
      content: userMessage,
      createdAt: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMessage]);

    try {
      const response = await fetch("/api/llm/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMessage,
          chatId: selectedChatId,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Failed to get response");
      }

      // Show notification if data was stored
      if (data.dataStored) {
        toast.success(`✅ Data stored: ${data.dataCount} record(s) added to database`);
      }

      // Add assistant response
      const assistantMessage: Message = {
        id: Date.now() + 1,
        role: "assistant",
        content: data.response,
        createdAt: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMessage]);

      // Update selected chat or create new one
      if (data.chatId !== selectedChatId) {
        setSelectedChatId(data.chatId);
        await fetchChats();
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to send message");
      // Remove the temp user message on error
      setMessages((prev) => prev.filter((m) => m.id !== tempUserMessage.id));
    } finally {
      setIsLoading(false);
    }
  };

  const handleNewChat = () => {
    setSelectedChatId(null);
    setMessages([]);
    setInput("");
  };

  return (
    <div className="flex h-[calc(100vh-200px)] gap-4 min-h-0">
      {/* Sidebar - Chat History */}
      <div className="w-64 card p-4 flex-shrink-0">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-text">Chat History</h2>
          <button
            onClick={handleNewChat}
            className="btn-primary text-sm px-3 py-1"
          >
            New Chat
          </button>
        </div>
        <div className="space-y-2 overflow-y-auto max-h-[calc(100vh-300px)]">
          {chats.map((chat) => (
            <button
              key={chat.id}
              onClick={() => setSelectedChatId(chat.id)}
              className={`w-full text-left p-2 rounded-lg transition ${
                selectedChatId === chat.id
                  ? "bg-accent/20 border border-accent"
                  : "bg-surface2 hover:bg-surface border border-border"
              }`}
            >
              <div className="text-sm font-semibold text-text truncate">
                {chat.title || "New Chat"}
              </div>
              <div className="text-xs text-textSecondary">
                {new Date(chat.createdAt).toLocaleDateString()}
              </div>
            </button>
          ))}
          {chats.length === 0 && (
            <p className="text-sm text-textSecondary text-center py-4">
              No chat history. Start a new conversation!
            </p>
          )}
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 card p-6 flex flex-col min-h-0 overflow-hidden">
        <div className="flex-1 chat-messages-container mb-4 space-y-4" style={{ paddingRight: '1rem' }}>
          {messages.length === 0 ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <h3 className="text-xl font-bold text-text mb-2">
                  NBA Analytics Assistant
                </h3>
                <p className="text-textSecondary">
                  Ask me anything about NBA games, players, odds, or historical data!
                </p>
                <div className="mt-4 p-4 bg-surface2 border border-border rounded-lg text-sm text-textSecondary space-y-2 pr-6">
                  <p className="mb-2 pr-2">
                    💡 <strong>Tip:</strong> Connect your own LLM API key in{" "}
                    <a href="/settings" className="text-accent hover:underline">
                      Settings
                    </a>{" "}
                    to use OpenAI, Anthropic (Claude), or Google (Gemini).
                  </p>
                  <p className="mb-2 pr-2">
                    📊 <strong>Data Generation:</strong> Ask me to add or create data! For example:
                  </p>
                  <ul className="list-disc list-inside ml-2 space-y-1 pr-2">
                    <li>"Add a game between Lakers and Warriors on Nov 20, 2024"</li>
                    <li>"Create player stats for LeBron James: 25 points, 8 rebounds, 7 assists"</li>
                    <li>"Add injury: Anthony Davis, Lakers, Questionable, knee soreness"</li>
                    <li>"Provide odds for Lakers vs Warriors: spread -4.5, total 225.5"</li>
                  </ul>
                  <p className="text-xs mt-2 pr-2">
                    I'll automatically store the data in the database for your models to use!
                  </p>
                </div>
                <div className="mt-4 text-sm text-textSecondary pr-6">
                  <p className="pr-2">Try asking:</p>
                  <ul className="list-disc list-inside mt-2 space-y-1 pr-2">
                    <li>"What are the upcoming games?"</li>
                    <li>"Show me player stats for LeBron James"</li>
                    <li>"What are the current betting odds?"</li>
                    <li>"Show me historical odds trends"</li>
                  </ul>
                </div>
              </div>
            </div>
          ) : (
            messages.map((message) => (
              <div
                key={message.id}
                className={`flex ${
                  message.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                <div
                  className={`max-w-[85%] rounded-lg p-4 break-words ${
                    message.role === "user"
                      ? "bg-accent text-white"
                      : "bg-surface2 text-text border border-border"
                  }`}
                >
                  <div className="whitespace-pre-wrap chat-message-content pr-2">{message.content}</div>
                </div>
              </div>
            ))
          )}
          {isLoading && (
            <div className="flex justify-start">
              <div className="bg-surface2 text-text border border-border rounded-lg p-4">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 bg-accent rounded-full animate-bounce"></div>
                  <div className="w-2 h-2 bg-accent rounded-full animate-bounce" style={{ animationDelay: "0.2s" }}></div>
                  <div className="w-2 h-2 bg-accent rounded-full animate-bounce" style={{ animationDelay: "0.4s" }}></div>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <form onSubmit={handleSend} className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question about NBA data..."
            className="flex-1 bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all"
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}


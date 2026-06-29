"use client";

import { useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import { Play, Save, Download, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface CodeEditorProps {
  initialValue?: string;
  language?: string;
  height?: string;
  onExecute?: (code: string) => void;
  onSave?: (code: string) => void;
}

const LANGUAGES = [
  { value: "python", label: "Python" },
  { value: "javascript", label: "JavaScript" },
  { value: "typescript", label: "TypeScript" },
  { value: "json", label: "JSON" },
  { value: "yaml", label: "YAML" },
  { value: "markdown", label: "Markdown" },
  { value: "html", label: "HTML" },
  { value: "css", label: "CSS" },
  { value: "sql", label: "SQL" },
  { value: "shell", label: "Shell" },
  { value: "rust", label: "Rust" },
  { value: "go", label: "Go" },
];

export function CodeEditor({
  initialValue = "",
  language = "python",
  height = "400px",
  onExecute,
  onSave,
}: CodeEditorProps) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const editorRef = useRef<any>(null);
  const [currentLanguage, setCurrentLanguage] = useState(language);
  const [isExecuting, setIsExecuting] = useState(false);

  const handleExecute = async () => {
    if (!editorRef.current || !onExecute) return;
    
    setIsExecuting(true);
    try {
      const code = editorRef.current.getValue();
      await onExecute(code);
    } finally {
      setIsExecuting(false);
    }
  };

  const handleSave = () => {
    if (!editorRef.current || !onSave) return;
    const code = editorRef.current.getValue();
    onSave(code);
  };

  const handleDownload = () => {
    if (!editorRef.current) return;
    const code = editorRef.current.getValue();
    const blob = new Blob([code], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `code.${currentLanguage === "python" ? "py" : currentLanguage}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !editorRef.current) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      editorRef.current.setValue(content);
    };
    reader.readAsText(file);
  };

  return (
    <div className="border rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-muted border-b">
        <div className="flex items-center gap-2">
          <Select value={currentLanguage} onValueChange={(v) => setCurrentLanguage(v || "python")}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LANGUAGES.map((lang) => (
                <SelectItem key={lang.value} value={lang.value}>
                  {lang.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="file"
            id="file-upload"
            className="hidden"
            onChange={handleFileUpload}
            accept=".py,.js,.ts,.json,.yaml,.yml,.md,.html,.css,.sql,.sh,.rs,.go"
          />
          <label htmlFor="file-upload" className="cursor-pointer">
            <Button variant="outline" size="sm" type="button">
              <Upload className="h-4 w-4 mr-1" />
              Load
            </Button>
          </label>

          <Button variant="outline" size="sm" onClick={handleDownload}>
            <Download className="h-4 w-4 mr-1" />
            Save
          </Button>

          {onSave && (
            <Button variant="outline" size="sm" onClick={handleSave}>
              <Save className="h-4 w-4 mr-1" />
              Store
            </Button>
          )}

          {onExecute && (
            <Button
              size="sm"
              onClick={handleExecute}
              disabled={isExecuting}
            >
              {isExecuting ? (
                <>
                  <div className="h-4 w-4 mr-1 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  Running...
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 mr-1" />
                  Run
                </>
              )}
            </Button>
          )}
        </div>
      </div>

      <Editor
        height={height}
        language={currentLanguage}
        value={initialValue}
        onMount={(editor) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
        editorRef.current = editor;
        }}
        options={{
          minimap: { enabled: false },
          fontSize: 14,
          lineNumbers: "on",
          roundedSelection: false,
          scrollBeyondLastLine: false,
          automaticLayout: true,
          theme: "vs-dark",
        }}
      />
    </div>
  );
}

/**
 * The lucide-react icons this product may use (claude/ui-components.md). A new icon is a
 * deliberate choice: add it here in the same change that adds it to a component, so there is one
 * place that lists every icon in the UI. icon-allowlist.test.ts fails on an import that isn't on
 * this list — if that's you, you're probably adding a new icon on purpose; add it above and carry
 * on, same as updating src/brand/brand-lock.json after a brand re-sync.
 */
export const ALLOWED_ICONS = [
  "AlertCircle", "AlertTriangle", "ArchiveRestore", "ArrowLeft", "ArrowRightLeft", "ArrowUp",
  "ArrowUpDown", "BarChart3", "Brain", "Calculator", "CalendarPlus", "ChartColumnBig", "Check",
  "ChevronDown", "ChevronLeft", "ChevronRight", "ChevronUp", "ChevronsUpDown", "Circle",
  "CircleAlert", "CircleCheck", "ClipboardList", "Clock", "Copy", "Cpu", "Database",
  "DatabaseBackup", "Download", "ExternalLink", "Eye", "EyeOff", "FileBadge", "FileKey",
  "FileOutput", "FileSpreadsheet", "FileText", "FileUp", "Files", "Filter", "Fingerprint", "Folder",
  "FolderInput", "FolderKey", "FolderOpen", "FolderPlus", "FolderSync", "Gauge", "Globe",
  "HardDrive", "ImagePlus", "Info", "KeyRound", "Languages", "Loader2", "LoaderCircle", "Lock",
  "LockOpen", "LogIn", "LogOut", "Menu", "MessageSquare", "MessageSquareLock", "MessagesSquare",
  "MoreHorizontal", "Network", "NotebookText", "PanelLeft", "Paperclip", "Pause", "Pencil", "Pin", "PinOff",
  "Play", "Plus", "Printer", "RectangleEllipsis", "RefreshCw", "RotateCw", "ScrollText", "Search",
  "Server", "Settings", "Share2", "Shield", "ShieldOff", "Smartphone", "Square", "SquareTerminal",
  "Star", "StarOff", "Table2", "Trash2", "TriangleAlert", "Upload", "UserPlus", "UserRoundCheck",
  "UserRoundX", "Users", "UsersRound", "WifiOff", "X", "XCircle",
] as const;

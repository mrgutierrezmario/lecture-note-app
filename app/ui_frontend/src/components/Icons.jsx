// Stroke icons on a 24px grid, sized via the `size` prop and colored by currentColor.

const Svg = ({ size = 16, strokeWidth = 1.8, children, ...rest }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={strokeWidth}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    {...rest}
  >
    {children}
  </svg>
)

// Circled question mark — the User Guide link in the app bar.
export const HelpIcon = p => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7" />
    <circle cx="12" cy="17" r=".6" fill="currentColor" />
  </Svg>
)

export const GearIcon = p => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
  </Svg>
)

// "Aa" with an underline — key terms / spelling hints.
export const TermsIcon = p => (
  <Svg {...p}>
    <path d="M3 17l4-11 4 11M4.6 13h4.8M14 17v-6.5a2.5 2.5 0 0 1 5 0V17M14 13.5h5M3 21h18" />
  </Svg>
)

export const PauseIcon = p => (
  <Svg {...p}>
    <path d="M8 5v14M16 5v14" strokeWidth="2.4" />
  </Svg>
)

export const PlayIcon = p => (
  <Svg {...p}>
    <path d="M7 4l13 8-13 8z" fill="currentColor" stroke="none" />
  </Svg>
)

export const MicIcon = p => (
  <Svg {...p}>
    <rect x="9" y="2" width="6" height="12" rx="3" />
    <path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8" />
  </Svg>
)

export const TranscriptIcon = p => (
  <Svg {...p}>
    <path d="M4 6h16M4 12h10M4 18h14" />
  </Svg>
)

export const NotesIcon = p => (
  <Svg {...p}>
    <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
    <path d="M14 3v6h6M8 13h8M8 17h8" />
  </Svg>
)

export const AudioIcon = p => (
  <Svg {...p}>
    <path d="M9 18V6l12-2v12" />
    <circle cx="6" cy="18" r="3" />
    <circle cx="18" cy="16" r="3" />
  </Svg>
)

export const SparklesIcon = p => (
  <Svg strokeWidth={1.6} {...p}>
    <path d="M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8z" />
    <path d="M19 16l.9 2.1L22 19l-2.1.9L19 22l-.9-2.1L16 19l2.1-.9z" />
  </Svg>
)

export const UploadIcon = p => (
  <Svg {...p}>
    <path d="M12 16V4M6 10l6-6 6 6M4 20h16" />
  </Svg>
)

export const FileIcon = p => (
  <Svg {...p}>
    <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
    <path d="M14 3v6h6" />
  </Svg>
)

export const ChatIcon = p => (
  <Svg {...p}>
    <path d="M21 12a8 8 0 0 1-11.6 7.1L4 21l1.9-5.4A8 8 0 1 1 21 12z" />
  </Svg>
)

export const SendIcon = p => (
  <Svg strokeWidth={2} {...p}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Svg>
)

export const CloseIcon = p => (
  <Svg strokeWidth={2} {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Svg>
)

export const CheckIcon = p => (
  <Svg strokeWidth={2.5} {...p}>
    <path d="M5 12l5 5 9-10" />
  </Svg>
)

export const AlertIcon = p => (
  <Svg strokeWidth={2} {...p}>
    <path d="M12 9v4M12 17h.01" />
    <path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
  </Svg>
)

export const KeyIcon = p => (
  <Svg {...p}>
    <circle cx="8" cy="15" r="4" />
    <path d="M10.8 12.2L20 3M15 8l3 3M17 6l3 3" />
  </Svg>
)

export const MonitorIcon = p => (
  <Svg {...p}>
    <rect x="3" y="4" width="18" height="12" rx="2" />
    <path d="M8 20h8M12 16v4" />
  </Svg>
)

export const SunIcon = p => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Svg>
)

export const MoonIcon = p => (
  <Svg {...p}>
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
  </Svg>
)

export const LogoutIcon = p => (
  <Svg {...p}>
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
  </Svg>
)

export const UserIcon = p => (
  <Svg {...p}>
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21a8 8 0 0 1 16 0" />
  </Svg>
)

export const TrashIcon = p => (
  <Svg {...p}>
    <path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6" />
  </Svg>
)

export const HistoryIcon = p => (
  <Svg {...p}>
    <path d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5M12 7v5l3 2" />
  </Svg>
)

export const EditIcon = p => (
  <Svg {...p}>
    <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
  </Svg>
)

export const PlusIcon = p => (
  <Svg strokeWidth={2} {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
)

export const DriveIcon = p => (
  <Svg {...p}>
    <path d="M8 3h8l6 10-4 7H6l-4-7z" />
    <path d="M8 3l4 7M16 3l-4 7M2 13h20M12 10l-6 10" />
  </Svg>
)

export const DownloadIcon = p => (
  <Svg {...p}>
    <path d="M12 4v12M6 10l6 6 6-6M4 20h16" />
  </Svg>
)

export const AudioOffIcon = p => (
  <Svg {...p}>
    <path d="M9 18V6l12-2v12" />
    <circle cx="6" cy="18" r="3" />
    <circle cx="18" cy="16" r="3" />
    <path d="M3 3l18 18" />
  </Svg>
)

export const LockIcon = p => (
  <Svg {...p}>
    <rect x="5" y="11" width="14" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </Svg>
)

export const UnlockIcon = p => (
  <Svg {...p}>
    <rect x="5" y="11" width="14" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 7.5-2" />
  </Svg>
)


// Indeterminate spinner: an arc that rotates via the .spin CSS animation.
export const SpinnerIcon = p => (
  <Svg strokeWidth={2.2} className="spin" {...p}>
    <path d="M21 12a9 9 0 1 1-6.2-8.6" />
  </Svg>
)

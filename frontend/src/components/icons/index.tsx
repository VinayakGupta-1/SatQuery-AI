import { Icon, type IconProps } from './Icon'

/* Navigation and workspace ------------------------------------------------ */

/** New query: a signal returning from a target. */
export const AskIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M11 7.8v3.4l2.3 1.6" />
    <path d="m16.2 16.2 4 4" />
  </Icon>
)

export const HistoryIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M3.8 12a8.2 8.2 0 1 0 2.6-6" />
    <path d="M3.5 3.8v3.6h3.6" />
    <path d="M12 8v4.3l2.9 1.7" />
  </Icon>
)

export const SavedIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M6.5 4.2h11a1 1 0 0 1 1 1v14.3l-6.5-3.7-6.5 3.7V5.2a1 1 0 0 1 1-1Z" />
  </Icon>
)

/** Imagery: a framed scene with a horizon. */
export const ImageryIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="3.2" y="4.6" width="17.6" height="14.8" rx="2" />
    <path d="M3.4 15.2 8 11l3.4 3 3.2-2.6 5.9 4.6" />
    <circle cx="8.6" cy="8.8" r="1.4" />
  </Icon>
)

export const UploadIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M12 15.6V4.4" />
    <path d="m7.8 8.6 4.2-4.2 4.2 4.2" />
    <path d="M4.4 15v3.4a1.2 1.2 0 0 0 1.2 1.2h12.8a1.2 1.2 0 0 0 1.2-1.2V15" />
  </Icon>
)

/** Capability catalogue: a registry of instruments. */
export const CapabilityIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="3.4" y="3.4" width="7" height="7" rx="1.6" />
    <rect x="13.6" y="3.4" width="7" height="7" rx="1.6" />
    <rect x="3.4" y="13.6" width="7" height="7" rx="1.6" />
    <circle cx="17.1" cy="17.1" r="3.5" />
  </Icon>
)

export const ResultsIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4 19.4V9.8M9.3 19.4V5.2M14.7 19.4v-6.6M20 19.4V8" />
  </Icon>
)

export const ExportIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M12 4.4v11.2" />
    <path d="m7.8 11.4 4.2 4.2 4.2-4.2" />
    <path d="M4.4 15v3.4a1.2 1.2 0 0 0 1.2 1.2h12.8a1.2 1.2 0 0 0 1.2-1.2V15" />
  </Icon>
)

export const SettingsIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="2.9" />
    <path d="M12 3.2v2.3M12 18.5v2.3M20.8 12h-2.3M5.5 12H3.2M18.2 5.8l-1.6 1.6M7.4 16.6l-1.6 1.6M18.2 18.2l-1.6-1.6M7.4 7.4 5.8 5.8" />
  </Icon>
)

export const HelpIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.4" />
    <path d="M9.7 9.5a2.4 2.4 0 1 1 3.2 2.3c-.6.2-.9.7-.9 1.3v.5" />
    <path d="M12 16.7h.01" />
  </Icon>
)

/* Controls ---------------------------------------------------------------- */

export const MenuIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </Icon>
)

export const CloseIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="m6.4 6.4 11.2 11.2M17.6 6.4 6.4 17.6" />
  </Icon>
)

export const ChevronIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="m9 5.5 6.5 6.5L9 18.5" />
  </Icon>
)

export const ChevronDownIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="m5.5 9 6.5 6.5L18.5 9" />
  </Icon>
)

export const CollapseIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="3.4" y="4.4" width="17.2" height="15.2" rx="2" />
    <path d="M9.6 4.6v14.8" />
  </Icon>
)

export const SendIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4.6 12h13.8" />
    <path d="m12.8 6.4 5.6 5.6-5.6 5.6" />
  </Icon>
)

export const AttachIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M18.6 11.3 12.2 17.7a4.1 4.1 0 0 1-5.8-5.8l6.7-6.7a2.7 2.7 0 0 1 3.9 3.9l-6.6 6.6a1.3 1.3 0 0 1-1.9-1.9l6.1-6.1" />
  </Icon>
)

export const TrashIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4.8 6.6h14.4" />
    <path d="M9.4 6.5V5a1.2 1.2 0 0 1 1.2-1.2h2.8A1.2 1.2 0 0 1 14.6 5v1.5" />
    <path d="M6.6 6.6 7.5 19a1.2 1.2 0 0 0 1.2 1.1h6.6a1.2 1.2 0 0 0 1.2-1.1l.9-12.4" />
  </Icon>
)

export const CheckIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="m5 12.6 4.6 4.6L19 7.2" />
  </Icon>
)

export const AlertIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M12 3.8 21 19.4H3L12 3.8Z" />
    <path d="M12 9.8v4.1M12 16.9h.01" />
  </Icon>
)

export const InfoIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.4" />
    <path d="M12 11.2v5M12 7.9h.01" />
  </Icon>
)

export const RefreshIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M20 12a8 8 0 1 1-2.4-5.7" />
    <path d="M20.4 4.2v4.2h-4.2" />
  </Icon>
)

export const CopyIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="8.6" y="8.6" width="11" height="11" rx="1.8" />
    <path d="M15.4 5.4H6.2a1.8 1.8 0 0 0-1.8 1.8v9.2" />
  </Icon>
)

export const LogoutIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M14.8 7.6V5.4a1.4 1.4 0 0 0-1.4-1.4H5.8a1.4 1.4 0 0 0-1.4 1.4v13.2A1.4 1.4 0 0 0 5.8 20h7.6a1.4 1.4 0 0 0 1.4-1.4v-2.2" />
    <path d="M9.8 12h10.2" />
    <path d="m16.8 8.8 3.2 3.2-3.2 3.2" />
  </Icon>
)

/* Analysis and imagery ----------------------------------------------------- */

/** Scan: a swath crossing a frame. Used for the analysis state. */
export const ScanIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4 8V5.6a1.6 1.6 0 0 1 1.6-1.6H8M16 4h2.4A1.6 1.6 0 0 1 20 5.6V8M20 16v2.4a1.6 1.6 0 0 1-1.6 1.6H16M8 20H5.6A1.6 1.6 0 0 1 4 18.4V16" />
    <path d="M4 12h16" />
  </Icon>
)

export const LayersIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="m12 3.6 8.4 4.3-8.4 4.3-8.4-4.3L12 3.6Z" />
    <path d="m4.4 12.4 7.6 3.9 7.6-3.9" />
    <path d="m4.4 16.6 7.6 3.9 7.6-3.9" />
  </Icon>
)

export const GlobeIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.4" />
    <path d="M3.7 12h16.6" />
    <path d="M12 3.6c2.4 2.6 2.4 14.2 0 16.8-2.4-2.6-2.4-14.2 0-16.8Z" />
  </Icon>
)

export const ZoomInIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="10.8" cy="10.8" r="6.4" />
    <path d="M10.8 8.2v5.2M8.2 10.8h5.2M15.6 15.6l4 4" />
  </Icon>
)

export const ZoomOutIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="10.8" cy="10.8" r="6.4" />
    <path d="M8.2 10.8h5.2M15.6 15.6l4 4" />
  </Icon>
)

export const ResetIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="4" y="4" width="16" height="16" rx="2" />
    <path d="M9.4 9.4h5.2v5.2H9.4z" />
  </Icon>
)

export const FileIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M13.4 3.6H7.2A1.6 1.6 0 0 0 5.6 5.2v13.6a1.6 1.6 0 0 0 1.6 1.6h9.6a1.6 1.6 0 0 0 1.6-1.6V8.2Z" />
    <path d="M13.4 3.6v4.6h4.9" />
  </Icon>
)

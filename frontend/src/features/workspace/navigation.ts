import type { ComponentType } from 'react'
import type { IconProps } from '../../components/icons/Icon'
import {
  AskIcon,
  CapabilityIcon,
  ExportIcon,
  HelpIcon,
  HistoryIcon,
  ImageryIcon,
  SavedIcon,
  SettingsIcon,
} from '../../components/icons'

export interface NavItem {
  to: string
  label: string
  icon: ComponentType<IconProps>
  /** Match only the exact path, for the index route. */
  end?: boolean
  /** One line explaining the destination, shown in the collapsed rail. */
  description: string
}

export interface NavGroup {
  id: string
  label: string
  items: NavItem[]
}

/**
 * The whole navigable surface of the product, in five groups.
 *
 * Every entry here leads somewhere real and backed by something the service
 * actually does. Nothing is listed to look impressive: there is no "Models"
 * page because the backend exposes no model layer, and no "Datasets" library
 * because it stores no datasets between sessions.
 */
export const NAVIGATION: NavGroup[] = [
  {
    id: 'workspace',
    label: 'Workspace',
    items: [
      {
        to: '/',
        label: 'New query',
        icon: AskIcon,
        end: true,
        description: 'Ask a question of satellite imagery',
      },
      {
        to: '/history',
        label: 'History',
        icon: HistoryIcon,
        description: 'Analyses run in this session',
      },
      {
        to: '/saved',
        label: 'Saved queries',
        icon: SavedIcon,
        description: 'Questions kept for reuse',
      },
    ],
  },
  {
    id: 'data',
    label: 'Data',
    items: [
      {
        to: '/imagery',
        label: 'Imagery',
        icon: ImageryIcon,
        description: 'Rasters staged for the next analysis',
      },
    ],
  },
  {
    id: 'analysis',
    label: 'Analysis',
    items: [
      {
        to: '/capabilities',
        label: 'Capabilities',
        icon: CapabilityIcon,
        description: 'Every analysis this deployment can run',
      },
    ],
  },
  {
    id: 'results',
    label: 'Results',
    items: [
      {
        to: '/exports',
        label: 'Exports',
        icon: ExportIcon,
        description: 'Rasters produced by completed analyses',
      },
    ],
  },
  {
    id: 'system',
    label: 'System',
    items: [
      {
        to: '/settings',
        label: 'Settings',
        icon: SettingsIcon,
        description: 'Service, session and motion preferences',
      },
      {
        to: '/help',
        label: 'Help',
        icon: HelpIcon,
        description: 'How to phrase a query and what to upload',
      },
    ],
  },
]

import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button, StateBlock } from '../components/ui'
import { AlertIcon } from '../components/icons'

interface State {
  error: Error | null
}

/**
 * The last line of defence.
 *
 * A render error in one screen should not leave the operator staring at a
 * white page. The message shown is deliberately plain - the stack goes to the
 * console for a developer, never to the interface.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('SatQuery interface error', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="sq-page">
        <StateBlock
          icon={<AlertIcon size={20} />}
          tone="danger"
          title="Something in the interface stopped working"
          body="The analysis service is unaffected — this is a fault in the workspace itself. Reloading usually clears it."
          actions={
            <>
              <Button variant="primary" onClick={() => window.location.reload()}>
                Reload the workspace
              </Button>
              <Button variant="ghost" onClick={() => this.setState({ error: null })}>
                Try to continue
              </Button>
            </>
          }
        />
      </div>
    )
  }
}

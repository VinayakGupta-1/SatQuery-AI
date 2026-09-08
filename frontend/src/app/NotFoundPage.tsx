import { Link } from 'react-router-dom'
import { StateBlock } from '../components/ui'
import { GlobeIcon } from '../components/icons'

export function NotFoundPage() {
  return (
    <div className="sq-page">
      <StateBlock
        icon={<GlobeIcon size={20} />}
        title="Nothing at this address"
        body="The page you were looking for is not part of the workspace."
        actions={
          <Link to="/" className="sq-btn sq-btn--primary">
            Back to the query console
          </Link>
        }
      />
    </div>
  )
}

import { auth } from './auth'
import { licenses } from './licenses'
import { admins } from './admins'
import { audit } from './audit'

export { onUnauthorized, setTokenGetter } from './http'
export const api = { auth, licenses, admins, audit }

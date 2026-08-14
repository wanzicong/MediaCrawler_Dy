// Note: the `PrivateService` is only available when generating the client
// for local environments
import { OpenAPI, PrivateService } from "../../src/client"

OpenAPI.BASE =
  process.env.VITE_API_URL ||
  process.env.PLAYWRIGHT_BASE_URL ||
  "http://127.0.0.1:5173"

export const createUser = async ({
  email,
  password,
}: {
  email: string
  password: string
}) => {
  return await PrivateService.createUser({
    requestBody: {
      email,
      password,
      is_verified: true,
      full_name: "Test User",
    },
  })
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"

import {
  type Body_login_login_access_token as AccessToken,
  LoginService,
  type UserPublic,
  type UserRegister,
  UsersService,
} from "@/client"
import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from "@/lib/auth-token"
import { handleError } from "@/utils"
import useCustomToast from "./useCustomToast"

/**
 * 解析 JWT 的 exp 判断是否已过期。
 * 无 exp 或解析失败时按「未过期」处理，避免误踢掉非 JWT / 永不过期的 token；
 * 真正的鉴权仍以后端 401 为准（见 main.tsx 的 handleApiError）。
 */
const isTokenExpired = (token: string): boolean => {
  try {
    const payload = token.split(".")[1]
    if (!payload) return false
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/")
    const decoded = JSON.parse(atob(normalized))
    if (typeof decoded?.exp !== "number") return false
    return decoded.exp * 1000 <= Date.now()
  } catch {
    return false
  }
}

const isLoggedIn = () => {
  const token = getAccessToken()
  // 此前只判断 token 是否存在，不校验有效性 —— 过期 token 也能进入受保护页面。
  return token !== "" && !isTokenExpired(token)
}

const useAuth = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const { data: user } = useQuery<UserPublic | null, Error>({
    queryKey: ["currentUser"],
    queryFn: UsersService.readUserMe,
    enabled: isLoggedIn(),
  })

  const signUpMutation = useMutation({
    mutationFn: (data: UserRegister) =>
      UsersService.registerUser({ requestBody: data }),
    onSuccess: () => {
      navigate({ to: "/login" })
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })

  const login = async (data: AccessToken) => {
    const response = await LoginService.loginAccessToken({
      formData: data,
    })
    setAccessToken(response.access_token)
  }

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: () => {
      // 登录后必须让 currentUser 失效重取，否则 user 长期为 null，
      // 依赖它的导航/菜单/超管判定都不渲染。
      queryClient.invalidateQueries({ queryKey: ["currentUser"] })
      navigate({ to: "/" })
    },
    onError: handleError.bind(showErrorToast),
  })

  const logout = () => {
    clearAccessToken()
    // 清空缓存，避免退出后内存里残留上一用户的列表/详情数据。
    queryClient.clear()
    navigate({ to: "/login" })
  }

  return {
    signUpMutation,
    loginMutation,
    logout,
    user,
  }
}

export { isLoggedIn }
export default useAuth

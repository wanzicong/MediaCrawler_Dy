import { useQuery } from "@tanstack/react-query"

import { DouyinUiService } from "@/client"
import { DEFAULT_ACCOUNT_STATUS_LABELS } from "@/components/Douyin/presentation"

/**
 * 账号状态文案：内置默认 + 后端文案覆盖。
 *
 * 文案由 `config.yaml` 的 `ui.labels.account_status` 下发（GET /douyin/ui-labels）。
 * 请求失败、接口缺键时都保持内置默认，因此文案接口不可用不影响页面。
 */
export function useAccountStatusLabels() {
  const labelsQuery = useQuery({
    queryKey: ["douyin-ui-labels"],
    queryFn: () => DouyinUiService.getUiLabels(),
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
  return {
    ...DEFAULT_ACCOUNT_STATUS_LABELS,
    ...(labelsQuery.data?.account_status ?? {}),
  }
}

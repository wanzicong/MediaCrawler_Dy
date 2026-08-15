import { toast } from "sonner"

const useCustomToast = () => {
  const showSuccessToast = (description: string) => {
    toast.success("操作成功", {
      description,
    })
  }

  const showErrorToast = (description: string) => {
    toast.error("操作失败", {
      description,
    })
  }

  return { showSuccessToast, showErrorToast }
}

export default useCustomToast

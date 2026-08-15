import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"

const ErrorComponent = () => {
  return (
    <main
      className="flex min-h-screen flex-col items-center justify-center p-4 text-center"
      data-testid="error-component"
    >
      <p className="text-sm font-medium text-destructive">页面加载异常</p>
      <h1 className="mt-2 text-2xl font-bold">暂时无法打开这个页面</h1>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        刚刚的操作没有完成，请稍后重试或返回工作台。
      </p>
      <Link to="/">
        <Button className="mt-5">返回工作台</Button>
      </Link>
    </main>
  )
}

export default ErrorComponent

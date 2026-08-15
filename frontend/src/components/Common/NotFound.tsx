import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"

const NotFound = () => {
  return (
    <main
      className="flex min-h-screen flex-col items-center justify-center p-4 text-center"
      data-testid="not-found"
    >
      <p className="text-5xl font-bold leading-none text-muted-foreground/50">
        404
      </p>
      <h1 className="mt-4 text-2xl font-bold">页面不存在</h1>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        这个地址可能已失效，或页面已经移动。
      </p>
      <Link to="/">
        <Button className="mt-5">返回工作台</Button>
      </Link>
    </main>
  )
}

export default NotFound

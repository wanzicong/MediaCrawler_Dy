import DeleteConfirmation from "./DeleteConfirmation"

const DeleteAccount = () => {
  return (
    <div className="mt-4 max-w-xl rounded-2xl border border-destructive/40 bg-destructive/[0.025] p-5 sm:p-6">
      <h3 className="font-semibold text-destructive">删除账号</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        永久删除你的账号及全部关联数据，此操作无法撤销。
      </p>
      <DeleteConfirmation />
    </div>
  )
}

export default DeleteAccount

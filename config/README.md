# 店铺示例怎么填图床

`shop.example.json` 仍使用 `"image_host": null`，新工作区不会默认绑定任何真实仓库。请把这一项替换为自己的配置：

```json
"image_host": {
  "type": "github",
  "repo": "your-account/your-images",
  "branch": "main",
  "base_url": "https://raw.githubusercontent.com/your-account/your-images/main"
}
```

这是字段片段，不能替换整份 shop.json。也可运行 image-host-setup --repo 账号/仓库名，先看预览，确认后加 --yes 自动写入。详细规则见 [店铺配置](../references/店铺配置.md)。图床必须公开，只放可公开的商品图片；不要把 shop.json、台账或登录资料放入图床。

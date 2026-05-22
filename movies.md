---
title: "MoVieS: Motion-Aware 4D Dynamic View Synthesis in One Second"
date: 2026-05-18
tags:
  - 3dgs
categories:
  - 3DGS
comment: true
toc: true
published: true
permalink: experience/3dgs
hexo-path:
---
#
<!--more-->

### 1. 高斯表示
- 每个高斯属性还是跟3dgs一样
### 2. 网络
- image encoder
	- DinoV2，来自vggt
- embedding
	- plucker_embedding
	- pose_embedding
	- time_embedding1
	- time_embedding2
- aggrator，来自vggt
- head
	- depth head，来自vggt
	- splat head
	- motion head，来自vggt的point head



1. 输入n帧视频：【N, 3, H, W】进入image encoder，得到image token【N，(H/14)\*(W/14)，1024】
2. 输入相机C2W【N，4，4】，fxfycxcy【N，4】，对每个像素计算射线o,d(u,v)后构造plucker（oxd, d）【N，6，H，W】，进入plucker_embed层（3d cov）得到plucker token【N，(H/14)\*(W/14)，1024】
3. 输入每帧时间t【N】，经过sim/cos编码得到time emb【N，T】(T=20)，然后通过time_embed线性层得到time token【N，1，1024】  
4. 输入相机C2W【N，4，4】，fxfycxcy【N，4】，转成W2C【N，4，4】，K【】，然后通过vggt的extri_intri_to_pose_encoding得到pose encoding【N，9】，大致对应R/t/fxfy 的 VGGT pose encoding，再经过线性层得到pose token【N，1，1024】 
5. 根据如下token构造input token【N，P+7，1024】 
	- patch token【N，(H/14)\*(W/14)，1024】
		- image token + plucker token
	- time token【N，1，1024】
	- pose token【N，1，1024】
	- camera_token 【N, 1, D】 # VGGT 原生 learnable camera token  
	- register_token【N, R, D】 # R=4，VGGT 原生 register tokens
6. 将input token输入aggrator，得到aggregated tokens list，每个元素【N，P+7，2048】（这里的2048是因为aggrator里面的frame attention与global aggention各1024个hidden）
7. 将aggregated tokens list输入三个head
	1. Depth head预测每帧深度，
		- 输入每层的aggregated tokens 的patchtoken部分【L，N，P，2048】
		- 输出深度图【N，1，H，W】与置信度【N，1，H，W】
		- 然后用深度 + 相机把每个像素 lift 到 canonical 3D 空间得到每个高斯的中心【N，3，H，W】
	2. Splat head：预测静态 Gaussian 属性，
		- 输入单层/多层aggregated tokens 【1，N，P，2048】，
		- 输出高斯属性【N，sh+3+4+1，H，W】与置信度【N，1，H，W】
	3. Motion head：预测动态偏移
		- 输入M帧目标时间t【M】，sin/cos编码得到time emb【M,T】，循环M次，对每个query time 单独跑 motion head，motion head 内部用 AdaLN以实现对不同时间的适应
		- 输出位置偏移量【M,N,3,H,W】与置信度【M,N,1,H,W】（为什么既有N又有M，motion head 要回答的是：对于第 m 个目标时间，所有输入高斯应该移动到哪里？）
		- motion_splat_head 输出其他属性偏移量【M,N,sh+3+4+1,H,W】
8. 将Depth head 与 Splat head输出结合得到anchor高斯，然后与Motion head输出结合得到目标高斯最后渲染得到结果视频【M,3,H,W】



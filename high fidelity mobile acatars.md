
### 0. 基础概念
1. 人体 avatar 是什么？
	- 一个可以被控制的三维数字人模型。可以根据输入姿态动起来，可以从任意相机视角渲染出图像。比如训练时这个人做了 A 动作，测试时你给一个新的骨骼姿态，它也能摆出新动作。
	- 在 WebAvatar 里，训练的核心不是“每一帧各建一个人”，而是：先建一个 canonical 人体 ，然后每一帧根据 SMPL-X pose 把它变形成当前动作（4dgs）
2. SMPL-X 是什么？
	- 一个**参数化人体模型**。它不是神经网络，不是生成模型，而是一个经典图形学/视觉里的人体模型。它的作用是：输入一组人体参数，  输出一个人体 mesh（包括人体顶点 vertices  人体骨架 joints  骨骼层级 kinematic tree  每个顶点的 skinning weights  手部、脸部、身体的形变基础）
	- 输入参数：betas 体型参数，  body_pose 身体各关节姿态，  global_orient 整个人的全局朝向，  transl 整个人的全局平移，  expression 表情参数，  jaw_pose 下巴姿态，  left_hand_pose / right_hand_pose 手部姿态。 本文主要用的输入：shape betas  ，body pose  ，expression
	- betas 是什么？
		- 它控制的是人的静态身体形状，比如：高矮  胖瘦  肩宽  腿长  手臂粗细  躯干比例  头身比例。该参数来自AvatarReX 数据集里的：smpl_params.npz。
3. LBS 是什么？
	- Linear Blend Skinning，一个点的位置 = 多根骨骼变换结果的加权平均

SMPL-X的输出不是一个mesh吗？怎么数据集作者将他训练到人体上输出的就是每一帧的人体姿态 + 这个人的 shape betas了？？既然数据集里面的SMPLX_NEUTRAL.npz是smplx生成的，在本文怎么有把他输入到一个smplx中？
为什么通用人体模板 + 这个人的 betas  = 这个人的 canonical 人体 mesh  ？我理解不了。你的意思是，betas+smpl-x(betas, pose, expression)=这个人的canonicalmesh？这样的话感觉betas重复了啊。
每组用自己的 local feature 和 local blendshape 建模是啥意思？每个组的这几个特征不一样？这些特征有是啥？


- 目标：用多视角人体视频训练一个 **可驱动的 3D Gaussian 人体 avatar**，然后让它能在手机、浏览器、PC 上高速渲染。
- 输入：一个人的多视角视频 + 每张图的人体 mask + 相机参数 + 每一帧的 SMPL-X pose / expression / shape 参数 +   SMPL-X neutral 模型文件
- 输出：一个可被新姿态驱动的人体 3D Gaussian Avatar  
- 用途：新视角渲染、新姿态动画、移动端实时运行
- 核心观是：人体局部区域里的 Gaussian 属性变化高度相关，比如手臂、裤子褶皱、衣服阴影，这些局部变化可以用局部线性模型表示，而不应该用一个全局 pose feature 控制全身。附近 Gaussians 的属性经常高度相关，所以把人体分成局部区域，用 local PCA / local blendshape 能更好地表达局部变化。
-

人体 avatar是啥？
用 SMPL-X 创建 canonical 人体模板是在干嘛，smplx这个模型干嘛用的？shape 参数 `betas` 又是哪来的，是啥？